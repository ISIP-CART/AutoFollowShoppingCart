"""Static contract checks for the integrated BLE range firmware.

These tests do not replace an ESP32 build or hardware validation.  They catch
accidental pin/protocol/safety drift with only Python's standard library.
"""

from pathlib import Path
import re
import unittest


FIRMWARE = Path(__file__).resolve().parents[1] / "esp32_at8236_velocity_ble.ino"


class FirmwareContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FIRMWARE.read_text(encoding="utf-8")

    def constant(self, name: str) -> int:
        match = re.search(
            rf"static const (?:u?int\d*_t|int|unsigned long|size_t) {name} = "
            rf"(0x[0-9A-Fa-f]+|\d+);",
            self.source,
        )
        self.assertIsNotNone(match, f"missing numeric constant {name}")
        return int(match.group(1), 0)

    def float_constant(self, name: str) -> float:
        match = re.search(
            rf"static const float {name} = (\d+(?:\.\d+)?)f;",
            self.source,
        )
        self.assertIsNotNone(match, f"missing float constant {name}")
        return float(match.group(1))

    def test_merge_is_resolved(self):
        self.assertNotIn("<<<<<<<", self.source)
        self.assertNotIn(">>>>>>>", self.source)

    def test_expected_bus_and_addresses(self):
        self.assertEqual(self.constant("I2C_SDA_PIN"), 21)
        self.assertEqual(self.constant("I2C_SCL_PIN"), 22)
        self.assertEqual(self.constant("LEFT_TOF_XSHUT_PIN"), 25)
        self.assertEqual(self.constant("RIGHT_TOF_XSHUT_PIN"), 26)
        self.assertEqual(self.constant("URM09_ADDRESS"), 0x11)
        self.assertEqual(self.constant("LEFT_TOF_ADDRESS"), 0x2A)
        self.assertEqual(self.constant("RIGHT_TOF_ADDRESS"), 0x2B)

    def test_safety_thresholds_and_freshness(self):
        self.assertEqual(self.constant("SENSOR_STALE_MS"), 200)
        self.assertEqual(self.constant("CENTER_STOP_MM"), 300)
        self.assertEqual(self.constant("CENTER_CLEAR_MM"), 400)
        self.assertEqual(self.constant("CORNER_STOP_MM"), 200)
        self.assertEqual(self.constant("CORNER_CLEAR_MM"), 300)
        self.assertEqual(self.constant("RISK_CLEAR_VALID_SAMPLES"), 3)
        self.assertEqual(self.constant("BRAKE_TELEMETRY_GRACE_MS"), 1500)
        self.assertEqual(self.constant("DRIVER_RECOVERY_ZERO_HOLD_MS"), 1000)
        self.assertIn("RANGE_MOTION_GATING_ENABLED = false", self.source)
        self.assertIn("REQUIRE_RANGE_SENSORS_FOR_MOTION = true", self.source)

    def test_sensor_motion_gating_is_bypassed_at_both_entries(self):
        block_reason = re.search(
            r"const char \*motionRangeBlockReason\(.*?\n\}",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(block_reason)
        self.assertRegex(
            block_reason.group(0),
            r"\{\s*if \(!RANGE_MOTION_GATING_ENABLED\) return NULL;",
        )

        active_safety = re.search(
            r"void serviceRangeMotionSafety\(\) \{.*?\n\}",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(active_safety)
        self.assertRegex(
            active_safety.group(0),
            r"\{\s*if \(!RANGE_MOTION_GATING_ENABLED\) return;",
        )

    def test_v1_sonar_capability_is_wired_end_to_end(self):
        self.assertIn('sendLine(source, "fCART_AT8236:s:r3v1:\\n")', self.source)
        self.assertIn("handleSonarFrequency(source, line)", self.source)
        self.assertIn("serviceLegacyRangeTelemetry();", self.source)
        self.assertIn(
            'sendLegacyTelemetryLine(source,\n'
            '                            "s" + String((minimumMm + 5) / 10)',
            self.source,
        )

    def test_r3_config_is_independent_strict_and_idempotent(self):
        self.assertEqual(self.constant("MIN_R3_REPORT_MS"), 100)
        self.assertEqual(self.constant("MAX_R3_REPORT_MS"), 1000)
        handler = re.search(
            r"void handleR3Config\(.*?\n\}", self.source, flags=re.DOTALL
        )
        self.assertIsNotNone(handler)
        body = handler.group(0)
        required_fragments = (
            'splitCsv(line, parts, 2) != 2',
            'parts[0] != "!R3"',
            'reportError(source, "bad_r3_config")',
            "r3ReportIntervalMs[index] = (unsigned long)requested",
            'sendLine(source, "!R3,OK," + String(requested) + "\\n")',
        )
        for fragment in required_fragments:
            self.assertIn(fragment, body)
        self.assertNotIn("r3Sequence[index]", body)
        self.assertNotIn("owner =", body)
        self.assertNotIn("ownerLastActivityMs", body)
        self.assertNotIn("lastMotionCommandMs", body)

    def test_r3_snapshot_has_fixed_lcr_order_status_and_saturated_age(self):
        self.assertIn('line = "!R3D,"', self.source)
        snapshot = re.search(
            r"String makeR3Snapshot\(.*?\n\}", self.source, flags=re.DOTALL
        )
        self.assertIsNotNone(snapshot)
        body = snapshot.group(0)
        self.assertLess(body.index("leftRange"), body.index("centerRange"))
        self.assertLess(body.index("centerRange"), body.index("rightRange"))
        required_fragments = (
            "if (!reading.present) return RANGE_NOT_PRESENT",
            "reading.status == RANGE_INVALID",
            "reading.status == SIGNAL_INVALID",
            "reading.status == RANGE_BUS_ERROR",
            "return RANGE_STALE",
            "status == RANGE_VALID",
            "? reading.filteredMm : -1",
            "if (reading.lastValidMs == 0) return UINT16_MAX",
            "return age > UINT16_MAX ? UINT16_MAX : (uint16_t)age",
            "uint16_t sequence = r3Sequence[sourceValue]++",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

    def test_ble_tx_is_20_byte_non_interleaving_latest_wins_queue(self):
        self.assertEqual(self.constant("BLE_TX_CHUNK_LEN"), 20)
        self.assertEqual(self.constant("BLE_TX_CHUNK_INTERVAL_MS"), 2)
        self.assertEqual(self.constant("BLE_TX_MAX_LINE_LEN"), 128)
        self.assertEqual(self.constant("MAX_PROTOCOL_LINE_LEN"), 127)
        required_fragments = (
            "void serviceBleTx()",
            "bleTxActiveLine.length() == 0",
            "bleTxPriorityCount > 0",
            "bleTxPendingR3Telemetry = line",
            "bleTxPendingLegacyTelemetry = line",
            "size_t chunkLength = min(remaining, BLE_TX_CHUNK_LEN)",
            "now - lastBleTxChunkMs < BLE_TX_CHUNK_INTERVAL_MS",
            "bleTxActiveOffset += chunkLength",
            "serviceR3Telemetry();",
            "serviceBleTx();",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

        loop = re.search(r"void loop\(\) \{(.*?)\n\}", self.source, flags=re.DOTALL)
        self.assertIsNotNone(loop)
        self.assertLess(loop.group(1).index("serviceR3Telemetry();"),
                        loop.group(1).index("serviceBleTx();"))

    def test_r3_ble_session_resets_on_disconnect_and_connect(self):
        events = re.search(
            r"void serviceBleEvents\(\) \{.*?\n\}", self.source, flags=re.DOTALL
        )
        self.assertIsNotNone(events)
        body = events.group(0)
        self.assertGreaterEqual(body.count("r3ReportIntervalMs[SOURCE_BLE] = 0"), 2)
        self.assertGreaterEqual(body.count("r3Sequence[SOURCE_BLE] = 0"), 2)
        self.assertGreaterEqual(body.count("clearBleTxState();"), 2)

    def test_unfrozen_v2_commands_are_not_implemented(self):
        process_match = re.search(
            r"void processCommand\(.*?\n\}", self.source, flags=re.DOTALL
        )
        self.assertIsNotNone(process_match)
        process_command = process_match.group(0)
        for header in ("m", "d", "g", "a"):
            self.assertNotIn(f"line.charAt(0) == '{header}'", process_command)

    def test_sensor_poll_and_safety_precede_motor_update(self):
        loop_match = re.search(r"void loop\(\) \{(.*?)\n\}", self.source, flags=re.DOTALL)
        self.assertIsNotNone(loop_match)
        loop = loop_match.group(1)
        self.assertLess(loop.index("serviceRangeSensors();"), loop.index("serviceBleEvents();"))
        self.assertLess(loop.index("serviceRangeMotionSafety();"), loop.index("serviceActiveMotion();"))
        self.assertLess(loop.index("serviceBrake();"), loop.index("serviceDriverRecovery();"))
        self.assertIn("serviceLegacyRangeTelemetry();", loop)
        self.assertIn("serviceR3Telemetry();", loop)
        self.assertIn("serviceBleTx();", loop)
        self.assertIn("serviceRangeDiagnostics();", loop)

    def test_non_range_safety_paths_remain_present(self):
        required_fragments = (
            'beginBrake("control_zero")',
            'line.startsWith("!S")',
            'beginBrake("link_timeout")',
            'beginBrake("motion_timeout")',
            'enterDriverFault("driver_boot_timeout", false)',
            'beginBrake("direct_reversal")',
            'beginBrake("ble_disconnect")',
            'enterLatchedFault(EMERGENCY_STOP',
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

    def test_transient_driver_faults_stop_then_recover_from_fresh_zero_mspd(self):
        required_fragments = (
            'beginBrake("telemetry_timeout_while_moving")',
            'enterDriverFault("mspd_lost_while_braking", true)',
            'enterDriverFault("brake_timeout", true)',
            "void serviceDriverRecovery()",
            "!mspdFresh() || !allWheelsNearZero()",
            "DRIVER_RECOVERY_ZERO_HOLD_MS",
            "setState(READY_STOP)",
            'diagnostic("driver_recovered"',
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

        self.assertNotIn(
            'enterLatchedFault(DRIVER_ERROR, "telemetry_timeout_while_moving")',
            self.source,
        )
        self.assertNotIn(
            'enterLatchedFault(DRIVER_ERROR, "mspd_lost_while_braking")',
            self.source,
        )

    def test_feedback_direction_and_overspeed_remain_hard_faults(self):
        self.assertIn(
            'enterDriverFault("feedback_sign_mismatch_m" + String(i + 1), false)',
            self.source,
        )
        self.assertIn(
            'enterDriverFault("overspeed_absolute_m" + String(i + 1), false)',
            self.source,
        )
        self.assertIn(
            'enterDriverFault("overspeed_dynamic_m" + String(i + 1), false)',
            self.source,
        )
        self.assertIn("Hard faults and emergency stop must remain in disabled-PWM mode", self.source)
        self.assertIn("disablePwmOutput();", self.source)

    def test_c14_and_curve_captures_do_not_false_hard_overspeed(self):
        warning_ratio = self.float_constant("OVERSPEED_WARNING_RATIO")
        hard_ratio = self.float_constant("OVERSPEED_RATIO")
        minimum = self.float_constant("OVERSPEED_MIN_MMPS")
        absolute = self.float_constant("OVERSPEED_ABSOLUTE_MMPS")

        def limit(target: float, ratio: float) -> float:
            return min(absolute, max(minimum, abs(target) * ratio))

        self.assertEqual(warning_ratio, 1.5)
        self.assertEqual(hard_ratio, 4.0)
        self.assertGreater(437.92, limit(240, warning_ratio))
        self.assertLess(437.92, limit(240, hard_ratio))
        self.assertLess(437.92, limit(223, hard_ratio))
        self.assertGreater(533.12, limit(154, 3.0))
        self.assertLess(533.12, limit(154, hard_ratio))
        self.assertEqual(limit(600, hard_ratio), 750.0)
        self.assertIn('diagnostic("overspeed_warning"', self.source)

    def test_curve_target_reduction_waits_for_command_and_feedback_settle(self):
        self.assertEqual(self.constant("OVERSPEED_TARGET_SETTLE_MS"), 500)
        required_fragments = (
            "speedReference = max(absFloat((float)currentWheelMmps[i])",
            "currentWheelMmps[i] == targetWheelMmps[i]",
            "now - targetSettledSinceMs[i] >= OVERSPEED_TARGET_SETTLE_MS",
            "dynamicCheckSettled && absFloat(measured) > limit",
            "if (targetWheelMmps[i] != requested[i])",
            "targetSettledSinceMs[i] = 0",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

        absolute_check = self.source.index(
            "absFloat(measured) > OVERSPEED_ABSOLUTE_MMPS"
        )
        settled_check = self.source.index("bool dynamicCheckSettled")
        self.assertLess(absolute_check, settled_check)

    def test_fault_context_is_persistent_and_queryable(self):
        required_fragments = (
            "recordFaultContext(reason, recoverable)",
            'Serial.print(",last_fault_reason=")',
            'Serial.print(",last_fault_at_ms=")',
            'Serial.print(",last_fault_recoverable=")',
            'Serial.print(",driver_recovery_active=")',
            'Serial.print(",fault_mspd_age_ms=")',
            'Serial.print(",fault_target=")',
            'Serial.print("fault_current=")',
            'Serial.print("fault_mspd=")',
            'Serial.println("FAULT_RECOVERY,version=3,transient_auto_recover=1,overspeed_hard_ratio=4.00,overspeed_absolute_mmps=750")',
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

    def test_range_observation_outputs_remain_present(self):
        required_fragments = (
            'line == "!D,1"',
            'Serial.print("RANGE,ms=")',
            'Serial.print(",left_status=")',
            'Serial.print(",center_status=")',
            'Serial.print(",right_status=")',
            'Serial.print(",risk=")',
            'Serial.print(",gating=")',
            'Serial.print(",range_motion_gating=")',
            'Serial.println("RANGE_MODE,mode=LOG_ONLY,gating=0")',
            'Serial.println("R3_PROTOCOL,version=R3-V1,tx_chunk_bytes=20,range_gating=0")',
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

    def test_recovery_drops_pre_stale_filter_history(self):
        self.assertIn("now - reading.lastValidMs > SENSOR_STALE_MS", self.source)
        self.assertIn("reading.historyCount = 0", self.source)


if __name__ == "__main__":
    unittest.main()
