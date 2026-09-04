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
            rf"static const (?:u?int\d*_t|int|unsigned long) {name} = "
            rf"(0x[0-9A-Fa-f]+|\d+);",
            self.source,
        )
        self.assertIsNotNone(match, f"missing numeric constant {name}")
        return int(match.group(1), 0)

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
        self.assertIn('sendLine(source, "fCART_AT8236:s:\\n")', self.source)
        self.assertIn("handleSonarFrequency(source, line)", self.source)
        self.assertIn("serviceLegacyRangeTelemetry();", self.source)
        self.assertIn('sendLine(source, "s" + String((minimumMm + 5) / 10)', self.source)

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
        self.assertIn("serviceLegacyRangeTelemetry();", loop)
        self.assertIn("serviceRangeDiagnostics();", loop)

    def test_non_range_safety_paths_remain_present(self):
        required_fragments = (
            'beginBrake("control_zero")',
            'line.startsWith("!S")',
            'beginBrake("link_timeout")',
            'beginBrake("motion_timeout")',
            'enterLatchedFault(DRIVER_ERROR',
            'beginBrake("direct_reversal")',
            'beginBrake("ble_disconnect")',
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
        )
        for fragment in required_fragments:
            self.assertIn(fragment, self.source)

    def test_recovery_drops_pre_stale_filter_history(self):
        self.assertIn("now - reading.lastValidMs > SENSOR_STALE_MS", self.source)
        self.assertIn("reading.historyCount = 0", self.source)


if __name__ == "__main__":
    unittest.main()
