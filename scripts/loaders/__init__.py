"""File-format loaders that sit BELOW the engine.

Nothing in here imports pygame, a component, or the renderer. These modules
turn bytes on disk into plain Python and back, so they can be exercised by a
tool with no display and no game loop.

    map_document  read/write .tmx with byte-faithful round trips
    map_loader    (empty) reserved for the pytmx -> scene-graph spawn path
"""
