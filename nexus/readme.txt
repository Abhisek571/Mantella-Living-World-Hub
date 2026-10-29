Mantella Living World - Integration Hub
Version 1.0.0 by itsPigeon2000

The shared base of Mantella Living World. Install it once, then add the modules you want.
- Settings tab: Living World tabs in Mantella's UI for module status, token use, player and NPC overrides with presets, memories, prompt rules and settings.
- Memory: each NPC remembers talks from their own point of view, within a fixed budget. Edit or delete memories in the tab.
- Action gates: a gate is a rule saying who an action is for (close NPCs, followers or guards). Each NPC is offered only the actions whose gate fits them; hidden actions can't be run. Close means a friend or better, a party member, or engaged or married through Relationships; with Arousal, its own standing can make more NPCs close. Without Direct AI Connect nothing is filtered: sex, undress and marriage actions are offered to every NPC.
- Basic bio: NPCs with no bio get a short one from their race, sex, job, place, hold and guild. Overrides always win.
- Quiet outfits: hides Mantella's equip / unequip lines during scenes and after loading screens. The scene part needs OStim Expansion or Followers.
- Temperament: reserved, bold or forward per NPC. Aim at an NPC and press the hotkey (default Home). Needs the Arousal module. Pressing the hotkey with nobody targeted runs the setup.
- Module status: MCM page and a map in the tab with a check for each installed module and supported mod.
- Troubleshooting: MCM page Troubleshooting writes a report for bug reports (SKSE\Plugins\MantellaLivingWorld\report.txt) and has an optional debug log.
- One settings menu (MCM): Mantella Living World.

Requirements
- Mantella 0.14, with Advanced Actions turned on (Actions tab of Mantella's settings) for most Living World actions (bribe, persuade, marriage steps, positions, map marks and others)
- Mantella - Direct AI Connect (the patched Mantella.exe; memory, prompt rules, action gates and the tabs run inside it)
- SKSE, PapyrusUtil SE, MCM Helper, SkyUI
- Papyrus MessageBox - SKSE NG
Optional: the modules (OStim Expansion, Arousal, Relationships, Followers, World, Knowledge, Missives), each needs only this hub.

Before you start
1. Mantella 0.14: install it and check that a normal conversation works.
2. Mantella - Direct AI Connect: install it below Mantella in MO2 and run its Setup Backend.cmd once (needs Python 3.11). Without it the stock Mantella.exe runs and Living World does nothing.
3. Mantella Living World - Integration Hub, then the modules you want.
4. API key: your LLM service's key stays in GPT_SECRET_KEY.txt in the Mantella mod folder (in MO2, right-click Mantella, Open in Explorer). A key for another service goes in the file named on the Direct AI Connect page, next to it.
5. Open Mantella's settings page (http://localhost:4999/ui in your browser, only while Mantella is running), go to the Actions tab and turn on Advanced Actions. Many Living World actions (bribe, persuade, marriage steps, positions, map marks and others) only work with it, and it needs a model that supports tool calling.
6. Nothing happens? Living World Main Status in Mantella's settings page lists what is missing.

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
