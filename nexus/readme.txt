Mantella Living World - Integration Hub
Version 1.0.0 by itsPigeon2000

The shared base of Mantella Living World. Install it once, then add the modules you want.
- Settings tab: Living World tabs in Mantella's UI for module status, token use, player and NPC overrides with presets, memories, prompt rules and settings.
- Memory: each NPC remembers talks from their own point of view, within a fixed budget. Edit or delete memories in the tab.
- Action gates: each NPC is offered only the actions that fit them. Hidden actions can't be run.
- Basic bio: NPCs with no bio get a short one from their race, sex, job, place, hold and guild. Overrides always win.
- Quiet outfits: hides Mantella's equip / unequip lines during scenes and after loading screens. The scene part needs OStim Expansion or Followers.
- Temperament: reserved, bold or forward per NPC. Aim at an NPC and press the hotkey (default Home). Needs the Arousal module. Pressing the hotkey with nobody targeted runs the setup.
- Module status: MCM page and a map in the tab with a check for each installed module and supported mod.
- Troubleshooting: MCM page Troubleshooting writes a report for bug reports (SKSE\Plugins\MantellaLivingWorld\report.txt) and has an optional debug log.
- One settings menu (MCM): Mantella Living World.

Requirements
- Mantella 0.14, with Advanced Actions turned on (Actions tab of Mantella's settings) for bribe, persuade and appetite rating
- Mantella - Direct AI Connect (the patched Mantella.exe; memory, prompt rules, action gates and the tabs run inside it)
- SKSE, PapyrusUtil SE, MCM Helper, SkyUI
- Papyrus MessageBox - SKSE NG
Optional: the modules (OStim Expansion, Arousal, Relationships, Followers, World, Knowledge, Missives), each needs only this hub.

Installation
1. Install with your mod manager and enable the plugin.
2. Install the modules you want; each needs only this hub: OStim Expansion, Arousal, Relationships, Followers.

Notes
- The World page in the MCM needs Mantella Living World - World.
- Mantella tip: lively scenes can send many in-game events at once. If replies come back empty, raise max_tokens in Mantella's LLM parameters from 250 to 500. It only gives the model room to finish; replies stay short.

Credits
- Mantella by Art from the Machine and contributors (AGPL-3.0)
- SKSE team
- PapyrusUtil SE by exiledviper and meh321
- MCM Helper by Parapets, SkyUI team
- Papyrus MessageBox - SKSE NG by mrowrpurr

License
GNU Affero General Public License v3.0 (see LICENSE.txt). Script sources are included in Scripts\Source.
Source code: https://github.com/Abhisek571/Mantella-Living-World-Hub
