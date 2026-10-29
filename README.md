# GLM-MD3-Extension

A Blender add-on for browsing Jedi Academy model files in PK3 archives and game directories, using MrWonko's and SomaZ's addons to import GLM and MD3 files directly from the PK3 archives into Blender. 

This project is experimental and assisted by AI.

First of all, let me make it clear that the only people that can get credits from this, are:
MrWonko for creating his marvelous addon that makes it possible for playermodel modding within blender.
* found here: https://github.com/mrwonko/Blender-Jedi-Academy-Tools

SomaZ for creating his incredible addon that makes mapping in Blender, md3 import/export, and so much more - possible within blender.
* found here: https://github.com/SomaZ/Blender_BSP_Importer

Arbiter for sharing a very critical document which he created after SomaZ gave him the missing piece of the puzzle.

## Installation

1. Download or clone this folder.
2. Install the folder as a Blender add-on through Blender's Preferences.
3. Enable **GLM-MD3-Extension** in the add-on preferences.
4. Ensure both addon's mentioned in the credits are installed and enabled, or you won't have a great time.

## Usage

In the 3D Viewport, open the **GLM/MD3 Extension** tab in the sidebar to access the add-on interface. 

### Initial Setup
1. Choose your game directory in the sidebar panel.
2. Once a valid game path is entered, the **Prepare ModView Directory** button becomes available. Click this to copy the game's `_humanoid` player assets into `<game base>/models/players/_humanoid` for compatibility with ModView.

### Browsing and Importing Models
Use the **Model Type** selector to browse specific model folders: `chunks`, `flags`, `items`, `map_objects`, `players`, `weaphits`, or `weapons2`. Map-object and weapon entries are grouped under non-selectable folder headings.

Each new model import automatically clears previously cached textures.

#### Weapon MD3 Imports
* **Import Weapon:** Imports the selected weapon MD3 along with its matching `_hand` MD3. If a matching `_barrel` MD3 exists, it is imported last.
* **Numbered Weapon Parts:** Same functionality as the previous, just makes it possible to import `weapon_name_x.md3` (where x is a number).
* **Import Selected MD3:** Imports strictly the selected `weapons2` MD3 without its companion hand or barrel files.
* **Scene Timeline:** A successful MD3 import automatically sets the scene end frame to 14.

#### Weapon Setup
Click **Setup Weapon** to automatically configure the weapon hierarchy:
* Connects the gun and hand tag hierarchy using a Copy Transforms constraint.
* Creates or updates an active **Weapon Preview Camera** at the origin with an 80-degree field of view and configured view shift.
* If a barrel MD3 is present, the setup parents its mesh to `tag_barrel.001` and adds a Copy Transforms constraint targeting the gun's `tag_barrel`.

#### GLM Imports and Skins
* **Weapon GLMs:** Imported via the GLM importer with no skin assigned. Textures from the same folder are staged in the cache.
* **Player GLMs:** Imported via the GLM importer while retaining their selected skin.
* **Skin Order:** Player skins are listed with `model_default.skin` first, followed by `model_red.skin`, `model_blue.skin`, and other `model_` skins.
* **Apply Skin:** For player models, this matches each scene mesh's `g2_prop.name` attribute to the selected `.skin` surface, assigns the corresponding texture from the cache, and updates mesh visibility. Surfaces set to `*off` in a skin are hidden; applying another skin updates them again.
* **Shader Textures:** Skin texture paths are resolved by checking supported file extensions and shader definitions. When a `.shader` file maps a shader name to an image, its first image map is used as the diffuse texture.

### Export Preparation
Under **Prepare for Export**, you can isolate components for clean exporting. Both options remove the weapon's Copy Transforms constraint from `tag_weapon` (without changing object parenting) and delete the **Weapon Preview Camera**.

* **Weapon:** Deletes the barrel mesh and the barrel tag.
* **Barrel:** Deletes the weapon mesh and the weapon tags, retains the barrel, renames the barrel tag to `tag_barrel`, and removes the Copy Transforms constraint from the retained tag.

### File Extraction
Use **Extract Model** to copy the selected model's entire folder, including all assets, beneath a chosen destination directory. For player models, the utility also reads all `.skin` files and extracts any additional player-model folders referenced by the underlying texture paths.

### Camera-Based Mesh Cleanup
With a mesh active, use **Remove Camera-Invisible Faces** to remove faces that are not hit by any viewport pixel ray. The button is enabled only while looking through the active scene camera (press Numpad 0 to enter camera view). The scan uses the actual 3D View, including visible areas outside the camera frame, and other scene geometry can occlude the active mesh.

The operation edits the active mesh directly, requires Object Mode, and does not support modifiers on that mesh. It scans every pixel within the mesh's projected viewport bounds. The confirmation dialog warns that Blender may briefly freeze during the scan. Visibility is based on opaque geometry and does not account for transparent materials or alpha cutouts.
