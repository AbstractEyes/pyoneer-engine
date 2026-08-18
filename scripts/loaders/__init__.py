"""File-format loaders that sit BELOW the engine.

Nothing in here imports pygame, a component, or the renderer. These modules
turn bytes on disk into plain Python and back, so they can be exercised by a
tool with no display and no game loop.

    map_document  read/write .tmx with byte-faithful round trips
    map_loader    a map's object layers -> constructed, placed entities
    tileset_file  the native .tileset declaration
    blitmap       the native .blitmap map format, and the tmx converter
    table_file    data/project/tables/*.json, the engine side of the
                  editor's Database -- the actors row a pyoneer_actor
                  names, which is rung 2 of behavior-parameter
                  resolution
"""
