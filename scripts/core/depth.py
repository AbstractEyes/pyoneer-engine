# Used to grab from the tiled map, but not really necessary for anything else.
MAP_DEPTH = {
    "Parallax":         1,  # the parallax background
    "Floor":            10, # the floor layer
    "ENTITY_1":         20, # the first entity layer
    "GroundClutter":    30, # the ground clutter layer
    "ENTITY_2":         40, # the second entity layer
    "PlayerDepth":      50, # the player depth layer
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