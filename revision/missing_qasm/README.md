# Figure 16 cache-only QASM stubs

These are not reconstructions of the original benchmark circuits. The released
IRIS dataset contains the exact `mapping.json` and `layers.json` used by the
Figure 16 runs, but omits these eight QASM inputs. `src/run.py` parses a QASM
before it checks the mapping/layer cache, even though the cached layers are the
actual scheduling input.

Each stub declares only the correct logical-qubit count. The Figure 16 runner
must use it only together with the released mapping/layer cache. If that cache
is absent or invalid, the run must fail rather than map this empty circuit.
