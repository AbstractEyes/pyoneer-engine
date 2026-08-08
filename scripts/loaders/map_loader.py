"""Reserved for the .tmx -> scene-graph spawn path. NOT IMPLEMENTED YET.

Deliberately left empty rather than filled with a guess. The read side of a
map currently goes straight from `AssetMapManager.load_assets` (pytmx) into
`GameMap`; the piece that does not exist is turning `<objectgroup>` entries
into live entities.

When that lands it belongs here, and it should read its object properties
through `scripts.loaders.map_document` (which types them) rather than pytmx
(which hands back every property as a string, so a depth of 50 arrives as
'50'). The writer half of that contract is already done and measured -- see
map_document.py and tools/check_tmx_roundtrip.py.
"""
