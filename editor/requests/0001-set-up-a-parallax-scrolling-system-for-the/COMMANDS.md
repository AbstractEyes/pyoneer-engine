# Command vocabulary

Every change to the project is one of these. Emit them as JSON
Lines -- one object per line -- into `response.jsonl`.

```json
{"verb": "map.tile.set", "scope": "map:test/layer:Floor", "args": {"x": 4, "y": 7, "gid": 65}}
```

Rules that are enforced, not suggested:

- Unknown verb, unknown argument, missing argument, or wrong
  argument type stops the whole response. Nothing is half-applied.
- Types are checked and never coerced. `"5"` is not `5`.
- A response is one transaction. One bad line rolls back the rest.

27 verbs:

### `map.layer.add`

Add a tile or object layer. A tile layer is created at the map's size. Note that a layer only RENDERS if its name has a depth in scripts/core/depth.py.

*Scopes:* `map:*`

| arg | type | required | meaning |
|---|---|---|---|
| `name` | str | yes | layer name; it is also the key the engine resolves to a draw depth |
| `kind` | str | no (default `'tile'`) | what sort of layer One of ['tile', 'object']. |
| `group` | str | no (default `''`) | name of a Tiled <group> to put it in; empty means beside the existing layers of its kind |
| `fill` | int | no (default `0`) | gid to fill a new tile layer with; 0 is empty |
| `index` | int | no (default `None`) | position among its siblings; omit to append |

```json
{"verb": "map.layer.add", "scope": "map:test", "args": {"name": "Hazard", "kind": "tile"}}
```

### `map.layer.remove`

Remove a layer and everything on it. The inverse restores the whole element, its tiles included.  **Destructive.**

*Scopes:* `map:*/layer:*`

| arg | type | required | meaning |
|---|---|---|---|
| `next_layer_id` | str | no (default `''`) | restore the map's nextlayerid to this after removing; used by undo |

### `map.layer.restore`

Put a layer back from a serialised payload, at its original position and with its original whitespace. The exact inverse of map.layer.remove; rarely written by hand.

*Scopes:* `map:*`

| arg | type | required | meaning |
|---|---|---|---|
| `payload` | dict | yes | as produced by MapDocument.serialize_layer |

### `map.layer.set`

Declare a capability on a layer -- depth, motion, parallax, opacity, occlusion, passability, whether it renders at all. Stored as a tmx custom property, so Tiled shows it too.

*Scopes:* `map:*/layer:*`

| arg | type | required | meaning |
|---|---|---|---|
| `key` | str | yes | capability name without the pyoneer_ prefix One of ['depth', 'motion', 'parallax_x', 'parallax_y', 'opacity', 'occludes', 'passability', 'renders']. |
| `value` | any | yes | int, float, str or bool, matching the capability's declared type |

```json
{"verb": "map.layer.set", "scope": "map:test/layer:Paralax", "args": {"key": "parallax_x", "value": 0.5}}
```

### `map.layer.unset`

Remove a declared capability, returning the layer to the default. The inverse of setting one that was not there.  **Destructive.**

*Scopes:* `map:*/layer:*`

| arg | type | required | meaning |
|---|---|---|---|
| `key` | str | yes | capability name without the pyoneer_ prefix |

### `map.object.add`

Place an object on an object layer. `type` is the class name the game resolves to a spawnable entity, so it must be a name the spawn registry knows.

*Scopes:* `map:*/layer:*`

| arg | type | required | meaning |
|---|---|---|---|
| `type` | str | yes | the object's class, e.g. 'Chest' or 'PlayerStart' |
| `x` | float | yes | world pixels from the left |
| `y` | float | yes | world pixels from the top |
| `name` | str | no (default `''`) | an instance name, unique within the layer by convention but not enforced |
| `width` | float | no (default `0.0`) | pixels; omit for a point object |
| `height` | float | no (default `0.0`) | pixels; omit for a point object |
| `gid` | int | no (default `0`) | tile gid, if this object draws as a tile |
| `properties` | dict | no (default `None`) | custom properties; types are inferred and written with an explicit tmx type attribute |
| `object_id` | int | no (default `0`) | force a specific id; leave unset and the document assigns the next free one |

```json
{"verb": "map.object.add", "scope": "map:test/layer:entity", "args": {"type": "Chest", "name": "chest_01", "x": 128, "y": 96, "properties": {"locked": true, "loot": "potion"}}}
```

### `map.object.move`

Move an object to new world-pixel coordinates.

*Scopes:* `map:*/layer:*/object:*`

| arg | type | required | meaning |
|---|---|---|---|
| `x` | float | yes | world pixels from the left |
| `y` | float | yes | world pixels from the top |

### `map.object.property.remove`

Remove a custom property from an object.  **Destructive.**

*Scopes:* `map:*/layer:*/object:*`

| arg | type | required | meaning |
|---|---|---|---|
| `key` | str | yes | property name |

### `map.object.property.set`

Set a custom property on an object. The tmx type attribute is written from the Python type, so an int reads back as an int rather than the string '50'.

*Scopes:* `map:*/layer:*/object:*`

| arg | type | required | meaning |
|---|---|---|---|
| `key` | str | yes | property name |
| `value` | any | yes | int, float, str or bool |

```json
{"verb": "map.object.property.set", "scope": "map:test/layer:entity/object:14", "args": {"key": "hp", "value": 30}}
```

### `map.object.remove`

Remove an object. Its inverse restores the whole XML element, so undo brings back shape, rotation and everything else.  **Destructive.**

*Scopes:* `map:*/layer:*/object:*`

*No arguments.*

```json
{"verb": "map.object.remove", "scope": "map:test/layer:entity/object:14", "args": {}}
```

### `map.object.restore`

Put back an object from its serialised XML, at its original position among its siblings. The exact inverse of map.object.remove; rarely written by hand.

*Scopes:* `map:*/layer:*`

| arg | type | required | meaning |
|---|---|---|---|
| `xml` | str | yes | the object's whole <object> element as XML text |
| `index` | int | no (default `None`) | position among sibling objects; omit to append |
| `next_object_id` | str | no (default `''`) | the map's nextobjectid before removal |

### `map.object.set`

Set a built-in attribute of an object. For anything else use map.object.property.set.

*Scopes:* `map:*/layer:*/object:*`

| arg | type | required | meaning |
|---|---|---|---|
| `key` | str | yes | which attribute One of ['name', 'type', 'class', 'width', 'height', 'gid', 'rotation', 'visible', 'template']. |
| `value` | str | yes | the new value, as text; tmx attributes are text |

### `map.object.unset`

Remove a built-in attribute entirely, rather than blanking it. The inverse of setting an attribute that was previously absent.  **Destructive.**

*Scopes:* `map:*/layer:*/object:*`

| arg | type | required | meaning |
|---|---|---|---|
| `key` | str | yes | which attribute to remove |

### `map.tile.fill`

Set every tile in a rectangle. The rectangle is clipped to the layer, so an over-large brush is a partial fill, not an error.

*Scopes:* `map:*/layer:*`

| arg | type | required | meaning |
|---|---|---|---|
| `x` | int | yes | left column |
| `y` | int | yes | top row |
| `width` | int | yes | columns |
| `height` | int | yes | rows |
| `gid` | int | yes | global tile id; 0 clears |

```json
{"verb": "map.tile.fill", "scope": "map:test/layer:Floor", "args": {"x": 0, "y": 0, "width": 8, "height": 4, "gid": 65}}
```

### `map.tile.set`

Set one tile's gid. gid 0 clears the tile.

*Scopes:* `map:*/layer:*`

| arg | type | required | meaning |
|---|---|---|---|
| `x` | int | yes | column, 0-based from the left |
| `y` | int | yes | row, 0-based from the top |
| `gid` | int | yes | global tile id from the map's tilesets; 0 is empty |

```json
{"verb": "map.tile.set", "scope": "map:test/layer:Floor", "args": {"x": 4, "y": 7, "gid": 65}}
```

### `map.tile.set_many`

Set many tiles at once. Cheaper and more readable than one command per tile, and it undoes as a single step.

*Scopes:* `map:*/layer:*`

| arg | type | required | meaning |
|---|---|---|---|
| `tiles` | list | yes | a list of [x, y, gid] triples, all integers |

```json
{"verb": "map.tile.set_many", "scope": "map:test/layer:Floor", "args": {"tiles": [[0, 0, 65], [1, 0, 65], [2, 0, 66]]}}
```

### `noop`

Does nothing. The inverse of a command that changed nothing.

*Scopes:* `project`

*No arguments.*

### `project.genre.set`

Switch the project's genre pack. Changes which layers and tables are expected and which panels the editor shows; does not delete anything.

*Scopes:* `project`

| arg | type | required | meaning |
|---|---|---|---|
| `genre` | str | yes | a genre pack id, e.g. 'platformer' |

```json
{"verb": "project.genre.set", "scope": "project", "args": {"genre": "platformer"}}
```

### `table.column.add`

Add a column. Existing rows take the default. This is how a genre grows -- adding 'stat_modifier' to equipment does not need editor code.

*Scopes:* `table:*`

| arg | type | required | meaning |
|---|---|---|---|
| `name` | str | yes | column name; snake_case by convention |
| `type` | str | yes | value type One of ['int', 'float', 'str', 'bool']. |
| `doc` | str | no (default `''`) | what it means |
| `default` | any | no (default `None`) | value for existing rows; omit for the type's zero |

```json
{"verb": "table.column.add", "scope": "table:weapons", "args": {"name": "damage", "type": "int", "doc": "hp removed per hit", "default": 1}}
```

### `table.column.remove`

Remove a column and every value in it. Refused for columns the genre marks required.  **Destructive.**

*Scopes:* `table:*/field:*`

*No arguments.*

### `table.column.restore`

Re-add a column and put its values back. The inverse of table.column.remove; rarely written by hand.

*Scopes:* `table:*`

| arg | type | required | meaning |
|---|---|---|---|
| `name` | str | yes | column name |
| `type` | str | yes | value type One of ['int', 'float', 'str', 'bool']. |
| `doc` | str | no (default `''`) | what it means |
| `default` | any | no (default `None`) | default value |
| `values` | dict | no (default `None`) | row id -> value |

### `table.create`

Create a data table. Prefer taking the genre's declared shape by leaving `columns` empty -- the pack already describes it.

*Scopes:* `table:*`

| arg | type | required | meaning |
|---|---|---|---|
| `title` | str | no (default `''`) | human label for the panel |
| `doc` | str | no (default `''`) | what this table is for |
| `columns` | list | no (default `None`) | list of {name, type, doc, default}; empty means take the genre's declaration |

```json
{"verb": "table.create", "scope": "table:actors", "args": {}}
```

### `table.drop`

Delete a table and its file. Refused for tables the genre marks required.  **Destructive.**

*Scopes:* `table:*`

| arg | type | required | meaning |
|---|---|---|---|
| `confirm` | bool | yes | must be true; guards against a stray drop |

### `table.restore`

Recreate a table from a full serialised payload. Exists so table.drop has an exact inverse; rarely written by hand.

*Scopes:* `table:*`

| arg | type | required | meaning |
|---|---|---|---|
| `table` | dict | yes | the table's full JSON, as table.to_json() |

### `table.row.add`

Add a row. Unlisted columns take their declared default.

*Scopes:* `table:*`

| arg | type | required | meaning |
|---|---|---|---|
| `id` | str | yes | the row's stable key, e.g. 'hero' or 'plasma_rifle' |
| `values` | dict | no (default `None`) | column -> value; every key must be an existing column and every value the declared type |

```json
{"verb": "table.row.add", "scope": "table:actors", "args": {"id": "hero", "values": {"display_name": "Hero", "hp": 30}}}
```

### `table.row.remove`

Remove a row. The inverse restores every value it held.  **Destructive.**

*Scopes:* `table:*/row:*`

*No arguments.*

### `table.row.set`

Set one cell.

*Scopes:* `table:*/row:*`

| arg | type | required | meaning |
|---|---|---|---|
| `column` | str | yes | which column |
| `value` | any | yes | the new value; must match the column's type |

```json
{"verb": "table.row.set", "scope": "table:actors/row:hero", "args": {"column": "hp", "value": 42}}
```
