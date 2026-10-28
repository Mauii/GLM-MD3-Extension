# GLM-MD3-Extension

A Blender add-on for browsing Jedi Academy model files in PK3 archives and game directories, then importing GLM models with their skins and textures.

This project is experimental.

## Installation

1. Download or clone this folder.
2. Install the folder as a Blender add-on through Blender's Preferences.
3. Enable **PK3 Model Browser** in the add-on preferences.
4. Ensure SomaZ's **Blender_BSP_Importer** add-on is enabled, as it is required for MD3 imports.
5. Ensure MrWonko's **Blender-Jedi-Academy-Tools** add-on is enabled, as it is required for GLM imports.

Both to be found here:
https://github.com/SomaZ/Blender_BSP_Importer
https://github.com/mrwonko/Blender-Jedi-Academy-Tools

The only people that should get credits for this, are: 
MrWonko for making jka playermodels modding possible
SomaZ for contributing in that project and for making md3 import/export possible (and all the other features of his plugin, do check it out!)
Arbiter for sharing critical knowledge (which he learned from SomaZ) that made the Weapon Modding part of this addon possible aswell.

## Usage

In the 3D Viewport, open the **GLM/MD3 Extension** tab in the sidebar to access the add-on interface. 

### Initial Setup
1. Choose your game directory in the sidebar panel.
2. Once a valid game path is entered, the **Prepare ModView Directory** button becomes available. Click this to copy the game's `_humanoid` player assets into `<game base>/models/players/_humanoid` for compatibility with ModView.

### Browsing and Importing Models
Use the **Model Type** selector to browse specific model folders: `chunks`, `flags`, `items`, `map_objects`, `players`, `weaphits`, or `weapons2`. Map-object and weapon entries are grouped under non-selectable folder headings.

#### Weapon MD3 Imports
* **Import Weapon:** Imports the selected weapon MD3 along with its matching `_hand` MD3. If a matching `_barrel` MD3 exists, it is imported last.
* **Numbered Weapon Parts:** For numbered parts (e.g., `blaster_rifle_1.md3`), the add-on uses the shared hand file (e.g., `blaster_rifle_hand.md3`). 
* **Import Selected MD3:** Imports strictly the selected `weapons2` MD3 without its eventual companion hand and/or barrel files.
* **Scene Timeline:** A successful MD3 import automatically sets the scene end frame to 14 so animation can be repeated.

#### Weapon Setup
Click **Setup Weapon** to automatically configure the weapon hierarchy:
* Connects the gun and hand tag hierarchy using a Copy Transforms constraint.
* Creates or updates an active **Weapon Preview Camera** at the origin with an 80-degree field of view and configured view shift.
* If a barrel MD3 is present, the setup parents its mesh to `tag_barrel.001` and adds a Copy Transforms constraint targeting the gun's `tag_barrel`.

#### GLM Imports and Skins
* **Weapon GLMs:** Imported via the GLM importer with no skin assigned. Textures from the same folder are staged in the cache.
* **Player GLMs:** Imported via the GLM importer while retaining their selected skin.
* **Apply Skin:** For player models, this matches each scene mesh's `g2_prop.name` attribute to the selected `.skin` surface and assigns the corresponding texture from the cache.

### Export Preparation
Under **Prepare for Export**, you can isolate components for clean exporting. Both options remove the weapon's Copy Transforms constraint from `tag_weapon` (without changing object parenting) and delete the **Weapon Preview Camera**.

Use the following after you've replaced a vanilla weapon mesh with yours.
* **Weapon:** Deletes the barrel mesh and the barrel tag.
* **Barrel:** Deletes the weapon mesh and the weapon tags, retains the barrel, renames the barrel tag to `tag_barrel`, and removes the Copy Transforms constraint from the retained tag.
* Both delete the created Camera aswell.

### File Extraction
Use **Extract Model** to copy the selected model's entire folder, including all assets, beneath a chosen destination directory. For player models, the utility also reads all `.skin` files and extracts any additional player-model folders referenced by the underlying texture paths.
