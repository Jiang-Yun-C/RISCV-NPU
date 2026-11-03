# T12 independent runtime fixtures

`tokenizer/tokenizer.nxt` contains all original vocabulary/merge and Unicode
normalization tables. Its manifest binds the original model lock and generator.
`inputs/` contains input-only C headers, small weight binaries, a sealed T11
linear tile, and separate Python/official-tokenizer expected results.

The CPU image links only the input headers. `golden.json` is consumed by the
independent checker, never by firmware or the active memory responder. Small
network dimensions are explicitly 1 layer, hidden/intermediate/vocabulary 64,
one Q/KV head; this is a port test, not a replacement for the full model.

Reproduce into a new directory:

```sh
npu-python model_tools/export_tokenizer.py build/my-runtime/tokenizer
npu-python tests/runtime/fixtures.py build/my-runtime/inputs
```

`make t12` compares every newly generated fixture against this publication
before executing the CPU. It then uses fresh ELF/images and distinct seed cases.
The contract is [runtime-v1](../../../../docs/spec/runtime-v1.md).
