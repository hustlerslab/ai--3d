"""Benchmark-only computer vision. NOT part of the pipeline.

Phase 0b evaluates whether an open-vocabulary detector identifies objects in a
moodboard render better than the scene reader does. Nothing in `app/` outside
this package may import it: the decision to adopt a detector has not been taken,
and a module the pipeline quietly starts depending on before the measurement is
in is exactly what the gate exists to prevent.

If the benchmark says adopt, the production home is `app/scene_understanding/`
and this package is deleted.
"""
