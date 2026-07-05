# ReID PC Test Workspace

`tools/reid_pc_test/` is the team's shared PC-side ReID research workspace.

What should be kept in Git:

- our own analysis scripts
- research notes
- lightweight configuration or usage notes
- selected upstream source code that the team needs to read locally

What must not be committed:

- `images/` because it may contain private photos
- `outputs/` because it may contain derived results tied to private photos
- `weights/` because model weights are large and should be managed separately

Repository boundary:

- `deep-person-reid/` is kept here as a normal directory for team reading and reference
- it is not treated as a Git submodule in this project
- if the team changes files inside it, those changes belong to this repository's history after the nested `.git` is removed

Upstream reference:

- original source: `https://github.com/KaiyangZhou/deep-person-reid`

Privacy rule:

- do not upload or publish any private person images without explicit permission
