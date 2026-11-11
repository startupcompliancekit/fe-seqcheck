# SeqCheck

**Turn a failing Fe state-machine test into a small, replayable regression.**

SeqCheck generates deterministic command sequences, checks an invariant after
every command, and reduces failures while preserving the original invariant ID.
The library and example are written in Fe. The same library tests run on the
native and EVM backends; the example CLI runs natively. No deployment is needed.

Fe developers have [asked for invariant fuzz testing](https://github.com/argotorg/fe/issues/1387).
This is a small library for testing explicit state models. It complements
`fe test` and external Foundry tests. It does not implement coverage-guided
fuzzing, deploy contracts, or provide Foundry integration.

## How this builds on Fe's standard library

Fe 26.5.0 already provides
[`std::evm::random`](https://github.com/argotorg/fe/blob/v26.5.0/ingots/std/src/evm/random.fe):
the `Rng` effect, seeded `KeccakRng`, supplied-word `ReplayRng`, unbiased
bounded sampling, and shuffle/choose helpers. Seeded randomness, random-word
replay and an injectable RNG effect are existing capabilities, not SeqCheck's
contribution.

SeqCheck adds a state-machine testing layer: resetting a model, executing a
command trace, checking invariants after every attempt (including rejected
commands), and recording the first failure ID. Its budgeted reducer removes
commands and shrinks their values while preserving that failure ID, producing
a trace that can be replayed as a regression. Standard `ReplayRng` repeats RNG
words; SeqCheck's `replay` executes model commands and checks invariants.

`StdEntropy<R>` connects an existing standard-library `Rng` to SeqCheck's
generator. It consumes exactly one 256-bit word per draw and retains its low
64 bits; `generate` then applies its documented modulo mapping. It does not
use `Rng.uniform`, promise unbiased sampling, or improve the supplied RNG's
security. The small `XorShift64` implementation remains a portable default
for the native demo, not a claim of a new RNG algorithm.

## Reproduce

Build requirements: Fe **26.5.0**, Python 3.10+ and a C compiler (`cc`).
No Python packages are required. From this repository root:

```sh
python3 scripts/install_fe.py
python3 scripts/check.py
```

The installer downloads one official compiler binary into `.tools/fe` and checks
its pinned SHA-256 before making it executable. It runs no remote installer or
global installation. If Fe 26.5.0 is already installed, skip the first command
and set `FE` to the verified compiler executable for `scripts/check.py`.

`check.py` checks formatting, runs the Fe suite on both backends, builds the
native example and runs an independent Python behavioral oracle. Detailed
results are written to `target/checks.json` and `target/*.log`. The CI workflow
runs these same commands.

The installer intentionally supports only Linux x86-64. Other platforms need
their own verified Fe 26.5.0 release and C linker.

## A failure you can explain

The example compares two views of a small ledger. Even command words deposit
`1 + (word / 2) % 8` units; odd words withdraw that amount if funds are available.
The intentionally faulty version decrements the second view by one unit too
little. Invariant **7** means the two views disagree.

```sh
./target/demo buggy 42 1000
./target/demo replay 0 1
./target/demo fixed 42 1000
./target/demo replay-fixed 0 1
```

The first two commands intentionally exit **1**, signalling a found failure.
The fixed versions exit **0**. Invalid arguments exit **2**. Each command emits
one JSON object; `scripts/verify.py` checks these results and exit codes.

For seed 42, the first failing prefix has six commands (five accepted). With a
1,000-candidate budget, it reduces to `[0,1]` in 17 candidate evaluations:
deposit one unit, then withdraw one unit. The corrected model passes the same
trace. Reproduce the record directly with `demo replay`, without a PRNG or seed.

Other useful cases:

```sh
./target/demo buggy 42 0
./target/demo replay
./target/demo replay 1 3 5
```

A zero budget retains the failing prefix and reports `exhausted: true`. An empty
or entirely rejected trace can have `failure: 0`; always inspect `attempted` and
`accepted` to distinguish useful exercise from no accepted operations.

## Use the library

Add a local path dependency to your ingot's `fe.toml`:

```toml
[dependencies]
seqcheck = { path = "../seqcheck" }
```

Implement `Machine` for your model:

```fe
use seqcheck::Machine

struct Model { count: u64 }

impl Machine for Model {
    fn reset(mut self) { self.count = 0 }
    fn step(mut self, _ word: u64) -> bool {
        if word == 0 && self.count < 10 {
            self.count += 1
            return true
        }
        false
    }
    fn invariant(self) -> u32 {
        if self.count <= 10 { 0 } else { 1 }
    }
}
```

Call `replay(mut model, trace)` or `reduce(mut model, trace, budget)`. See
[`src/tests.fe`](src/tests.fe) for working integrations. Traces are
`Trace<N> { words: [u64; N], len: usize }`; `N` is a compile-time capacity and
`len` is the meaningful prefix. Words beyond `len` are unspecified padding.

`generate<N>(len, upper)` consumes an explicit `Entropy` capability:

```fe
var rng = XorShift64::seeded(42)
let trace = with (Entropy = rng) { generate<64>(64, 16) }
```

Import `Entropy`, `XorShift64` and `generate` from `seqcheck`. Tests inject a
different entropy implementation without changing the generator. No ambient
clock, filesystem, chain state or host RNG affects the library.

To use a standard-library RNG instead:

```fe
use std::evm::random::ReplayRng
use seqcheck::{Entropy, StdEntropy, generate}

var rng = StdEntropy { rng: ReplayRng::new([1, 14, 12, 15]) }
let trace = with (Entropy = rng) { generate<8>(8, 16) }
```

The wrapped RNG remains available as `rng.rng` with its advanced state. Its
preconditions and backend requirements still apply: for example, `ReplayRng`
needs a nonempty word array when drawn, and `KeccakRng` uses EVM crypto helpers.
The adapter does not make EVM-specific operations available on the native
backend. Adapter tests use `ReplayRng` and a counting `Rng` on both backends;
they cover low-bit conversion, cyclic replay, draw counts, and a generated
trace reduced to a regression that fails on the buggy model and passes on the
corrected model.

## Architecture and contracts

- [`engine.fe`](src/engine.fe): model trait, replay records and bounded reducer.
- [`entropy.fe`](src/entropy.fe): injectable entropy, deterministic xorshift64
  and bounded word generation, plus the standard-library `Rng` adapter.
- [`ledger.fe`](src/ledger.fe): deliberately faulty/corrected demonstration model.
- [`examples/demo`](examples/demo): native JSON command-line example.
- [`scripts/verify.py`](scripts/verify.py): independent behavioral checks of the
  built executable; no Python implementation is used by the library.

`reset` must restore **all** state affecting execution. Each replay checks the
initial invariant and every attempted command, including rejected commands.
The first nonzero invariant ID stops execution. Use distinct stable IDs for
distinct defects, and return failures as IDs: a panic or hang cannot be caught
by this library and is handled only by the surrounding test process.

Reduction first removes the unexecuted suffix, then tries deleting individual
commands and replacing each word with zero or successive integer halves. It
repeats until a fixed point or budget exhaustion. Every accepted change must
reproduce the same first failure ID. The budget counts candidate replays,
excluding the baseline replay; each candidate executes at most `N` commands.

On a deterministic model, completed reduction is irreducible under those single
deletions and scalar substitutions. It is **not** guaranteed to be the shortest
possible trace or smallest numeric counterexample. A budget-exhausted result
still reproduces the failure but has no irreducibility guarantee. The model
object's final state is unspecified after reduction; replay the returned trace
to inspect it.

`Trace.len <= N` and generation `upper > 0` are asserted programmer
preconditions. Fixed arrays avoid heap allocation but use stack/linear memory
proportional to capacity. Use small capacities; the example caps traces at 64
and budgets at 10,000. Models must bound their own per-command work.

## Evidence and limits

The Fe suite covers reset, initial failures, empty capacity, rejection
accounting, failure-ID preservation, budget boundaries, fixed-point reduction,
entropy injection and deterministic streams. It includes 128 generated
64-command sequences for the corrected ledger. The independent oracle exercises
68 seeds, 341 exhaustive short traces, malformed arguments, integer boundaries
and replay of reduced failures, for 661 CLI invocations.

These are bounded tests, not a proof or security audit. The example is an
in-memory model and does not test deployed storage, transaction rollback,
reentrancy or gas behavior. Generation uses modulo mapping with slight bias;
xorshift64 is predictable and unsuitable for cryptography. Reduction operates
on raw words: a different domain may need its own validity-preserving encoding.
Fe 26.5.0 is experimental; this project does not claim production readiness.

## Provenance, AI assistance and license

Project code, tests and documentation were created for the November 2026 Fe
Builders Challenge, beginning November 9. No pre-existing project implementation
was imported. Fe 26.5.0 and its embedded standard library are external toolchain
dependencies. Fe documentation and standard-library examples informed API use.
The generator uses the established xorshift64 algorithm; shrinking uses
established deletion and numeric-reduction ideas. These algorithms are not
claimed as new inventions.

AI assistance was used for ecosystem research and for drafting and revising
code, tests and documentation. The reported verification consists of the
automated checks described above.

Licensed under the [MIT License](LICENSE), an OSI-approved license. The Fe
compiler and standard library retain their upstream Apache-2.0 license and are
not redistributed in this repository.
