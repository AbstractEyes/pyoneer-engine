# Used to grab from the tiled map, but not really necessary for anything else.
MAP_DEPTH = {
    "Parallax":         1,  # the parallax background
    "Floor":            10, # the floor layer
    "ENTITY_1":         20, # the first entity layer
    "GroundClutter":    30, # the ground clutter layer
    "ENTITY_2":         40, # the second entity layer
    "PlayerDepth":      50, # the player depth layer
    "Above1":           55, # authored in test.tmx between PlayerDepth and Foreground
    "Foreground":       60, # the foreground layer
    "ENTITY_3":         70, # the third entity layer
    "FOREGROUND_1":     80, # the first foreground layer
    "FOREGROUND_2":     90, # the second foreground layer
    "UI_LAYER_1":       100 # the first ui layer
}

OBJECT_DEPTH = {
    "ENTITY_BACKGROUND":    5, # background entities
    "ENTITY_FLOOR":         20, # Floor based entities
    "ENTITY":               50, # default entity layer
    "FOREGROUND_ENTITY":    80, # foreground effects and entities
    "UI_ENTITY":            100 # ui based entities
}

OBJECT_CONVERTER = {
    "GamePlayer": MAP_DEPTH["PlayerDepth"],
    "GameEntity": OBJECT_DEPTH["ENTITY"],
    "GameFloorEntity": OBJECT_DEPTH["ENTITY_FLOOR"],
    "GameBackgroundEntity": OBJECT_DEPTH["ENTITY_BACKGROUND"],
    "GameForegroundEntity": OBJECT_DEPTH["FOREGROUND_ENTITY"],
    "GameUIEntity": OBJECT_DEPTH["UI_ENTITY"],
}

DEPTH = MAP_DEPTH | OBJECT_DEPTH | OBJECT_CONVERTER

LAYER_NAME_ALIASES = {
    # data/maps/test.tmx spells this layer "Paralax" (one L). The layer holds
    # 39 real tiles that were silently dropped for as long as the renderer
    # looked up the correctly-spelled name. Aliasing rather than renaming the
    # layer keeps the .tmx byte-identical for Tiled; rename it in Tiled and
    # delete this entry whenever convenient.
    "Paralax": "Parallax",
}


def resolve_layer_depth(layer_name: str | None) -> int | None:
    """Depth for a map layer name, or None when the name is unmapped."""
    if layer_name is None:
        return None
    if layer_name in MAP_DEPTH:
        return MAP_DEPTH[layer_name]
    canonical = LAYER_NAME_ALIASES.get(layer_name)
    if canonical is not None:
        return MAP_DEPTH.get(canonical)
    return None