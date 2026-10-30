# Mantella Living World - Integration Hub

The shared base of Mantella Living World: one MCM, one settings tab in Mantella's UI, the memory system and the action gates every module uses.

| Module | What it adds | Repository |
|---|---|---|
| Integration Hub | The base: this repository | [Mantella-Living-World-Hub](https://github.com/Abhisek571/Mantella-Living-World-Hub) |
| Relationships | Marriage, family ties and shared history | [Mantella-Living-World-Relationships](https://github.com/Abhisek571/Mantella-Living-World-Relationships) |
| Arousal | Arousal, appetite and temperament | [Mantella-Living-World-Arousal](https://github.com/Abhisek571/Mantella-Living-World-Arousal) |
| OStim Expansion | OStim scenes run by conversation | [Mantella-Living-World-OStim-Expansion](https://github.com/Abhisek571/Mantella-Living-World-OStim-Expansion) |
| Followers | Party orders through Nether's Follower Framework | [Mantella-Living-World-Followers](https://github.com/Abhisek571/Mantella-Living-World-Followers) |
| World | Fame, bounty, war side, quest outcomes, banter | [Mantella-Living-World-World](https://github.com/Abhisek571/Mantella-Living-World-World) |
| Knowledge | What each NPC plausibly knows | [Mantella-Living-World-Knowledge](https://github.com/Abhisek571/Mantella-Living-World-Knowledge) |
| Missives | Job posters who know their own jobs | [Mantella-Living-World-Missives](https://github.com/Abhisek571/Mantella-Living-World-Missives) |
| Mantella - Direct AI Connect | The patched Mantella.exe that the settings tab, memory and prompt rules run inside | [Mantella-Anthropic-API](https://github.com/Abhisek571/Mantella-Anthropic-API) |

| Feature | What it does |
|---|---|
| Settings tab | Four Living World tabs in Mantella's UI: a module map with what needs attention, token use, player and NPC overrides with presets, memories, prompt rules and settings. Overrides can be exported and imported as a zip |
| Memory | Each NPC remembers talks from their own point of view, with a feeling about you and long-term notes, within a fixed budget. Edit, add or delete memories in the tab, one at a time or per NPC |
| Action gates | Each NPC is offered only the actions that fit them (close, follower, guard); hidden actions can't be run. If the hub can't tell, the gated action is not offered. Close means a friend or better, a party member, or engaged or married through Relationships; with Arousal, its own standing can make more NPCs close. Without Direct AI Connect nothing is filtered: sex, undress and marriage actions are offered to every NPC. Advanced Actions must be on in Mantella (Actions tab of http://localhost:4999/ui) for most Living World actions |
| Basic bio | NPCs with no bio get a short one from their race, sex, job, place, hold and guild. Overrides always win. For an NPC with no bio you can paste their Nexus page or notes in the tab and press Write bio with AI; it keeps only the character info and lists what it assumed |
| Override presets | Per NPC, a Version dropdown (Default, then the presets saved for that NPC). Save override preset names a preset; Delete preset removes it |
| Prompt rules | Each module adds short rule files to the system prompt |
| Quiet outfits | Mutes Mantella's equip and item events during scenes (needs OStim Expansion or Followers) and after loading screens |
| Temperament | Reserved, bold or forward per NPC, by hotkey or setup. Needs the Arousal module. The setup runs from the hotkey with nobody targeted |
| Troubleshooting | MCM page that writes a report for bug reports, and an optional debug log |
| Update check | Every 1 day by default (set the number of days, 0 = off), asks Nexus's public API whether an installed module has a newer version and marks it on the module map. Only the mods' Nexus IDs are sent, with no account or key. On by default only until Living World has been in use long enough to be sure it has no bugs left; after that it will be off by default |

Requires: [Mantella](https://www.nexusmods.com/skyrimspecialedition/mods/98631) 0.14, [Mantella - Direct AI Connect](https://github.com/Abhisek571/Mantella-Anthropic-API), [PapyrusUtil](https://www.nexusmods.com/skyrimspecialedition/mods/13048), [Papyrus MessageBox - SKSE NG](https://www.nexusmods.com/skyrimspecialedition/mods/83578), [MCM Helper](https://www.nexusmods.com/skyrimspecialedition/mods/53000), [SkyUI](https://www.nexusmods.com/skyrimspecialedition/mods/12604), SKSE. The modules are optional; each needs only this hub. Mantella's Advanced Actions should be on.

Build: `py -3 tools/build.py` builds every module (`--only hub` for this one). Tests: `py -3.11 server/tests/test_<name>.py server`.

License: GNU AGPL-3.0.
