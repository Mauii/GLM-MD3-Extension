# JAPluginSuite-extender

A Blender add-on for browsing Jedi Academy model files in PK3 archives and game
directories, then importing GLM models with their skins and textures.

Install this folder as a Blender add-on and enable **PK3 Model Browser** in
Blender's add-on preferences. In the 3D View, open the **PK3** tab in the
sidebar, choose the game directory, and select a model to import or apply a
skin.

Choose a model folder from the **Model Type** selector to browse `chunks`,
`flags`, `items`, `map_objects`, `players`, `weaphits`, or `weapons2`.
Map-object and weapon entries are grouped under non-selectable folder headings.
MD3 files are imported through Blender's **Import id Tech 3 BSP** add-on, which
must be enabled. Importing a `weapons2` MD3 also imports its matching `_hand`
MD3 and imports a matching `_barrel` MD3 last when one exists. Use **Setup
Weapon** to connect the gun and hand tag hierarchy with a Copy Transforms
constraint and create or update the active **Weapon Preview Camera** at the
origin with an 80-degree field of view and configured view shift. When a barrel
MD3 is present, setup parents its mesh to `tag_barrel.001` and adds a Copy
Transforms constraint targeting the gun's `tag_barrel`. Successful MD3 imports
set the scene end frame to 14. **Import Selected MD3** imports only the
selected `weapons2` MD3 without its hand or barrel companions. For numbered
weapon parts such as `blaster_rifle_1.md3` and `blaster_rifle_2.md3`,
**Import Weapon** imports only the selected part and uses the shared
`blaster_rifle_hand.md3` hand file. It prefers a numbered barrel such as
`blaster_rifle_1_barrel.md3`, falling back to `blaster_rifle_barrel.md3` when
that part's numbered barrel is absent. Select an individual part in the list
to set it up or prepare it for export independently.
Under **Prepare for Export**, choose **Keep Barrel** to delete the weapon mesh
and its tags, retaining the barrel and renaming its tag to `tag_barrel`, or
choose **Keep Weapon** to delete the barrel mesh and tag. Either choice removes
the weapon's Copy Transforms constraint from `tag_weapon` without changing
object parenting. **Keep Barrel** also removes the Copy Transforms constraint
from the retained `tag_barrel`. Either choice also deletes the
**Weapon Preview Camera**.
Weapon GLMs use the GLM importer with no skin assigned;
player GLMs continue to use their selected skin. Weapon MD3 imports also load
matching textures from the same model folder. Weapon GLM imports stage their
same-folder textures in the cache. Each model import clears previously cached
textures first.
For player models, **Apply Skin** matches each scene mesh's `g2_prop.name` to
the selected `.skin` surface and assigns its texture from the cache.
Use **Extract Model** to copy the selected model's entire folder, including all
files in that folder, beneath the chosen destination directory. For player
models, it also reads all `.skin` files and extracts any other player-model
folders referenced by their texture paths.
Use **Prepare ModView Directory** to copy the game's `_humanoid` player assets
into `<game base>/models/players/_humanoid` for ModView. This button is shown
once a game path has been entered.

This project is experimental.
