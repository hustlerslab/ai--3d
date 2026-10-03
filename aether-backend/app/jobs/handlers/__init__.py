"""Built-in job handlers. Importing this package registers them."""
from . import (  # noqa: F401
    analyze, build, element_images, film, generate, generate_elements, noop, repaint,
    repair_scene, scene_plan, smoke, tour, verify, viewpoints,
)
