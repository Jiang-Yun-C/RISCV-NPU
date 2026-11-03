# Model pack producer checks

`make t10-test` runs parser fault, numeric, replay and budget tests without the full checkpoint.
`make t10` exports and re-exports the entire locked adapted model, independently compares every
parameter, reproduces all fixtures, checks the runtime allocation budget, and runs project regression.

The versioned handoff is [fixtures/model_pack](../cocotb/fixtures/model_pack/manifest.json).
To regenerate into a new directory and independently check it:

```bash
npu-python tests/model_pack/generate_fixtures.py build/new-model-pack-fixtures
npu-python tests/model_pack/check_fixtures.py build/new-model-pack-fixtures --report build/fixture-check.json --negative-logs build/new-negative-logs
```

The independent checker imports neither the writer nor the T05 numeric implementation. It recomputes
quantization with scalar rounding and group dots with Python integer sums; FP32 operations follow the
frozen order. Bad-pack CLI runs retain nonzero exits. Fixtures are synthetic tensor collections, not
full-model inference or actual RTL tests. See [the format contract](../../docs/spec/model-pack-v1.md)
for T14/T15/T18 consumption and the K=65 unsupported-backend boundary.
