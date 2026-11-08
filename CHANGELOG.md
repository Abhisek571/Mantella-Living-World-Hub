# Changelog

Every change to Mantella Living World - Integration Hub. The Nexus page lists only the main changes for each version.

## Unreleased

### New
- Debug menu (MCM page, on by default): pick the last NPC you talked to, then set their relationship rank, M.A.R.A.S status and affection, and arousal, see what they can do right now, and reset everything you changed.
- New "intimate" check, used by the intimate actions: a lover, close in Relationships, an open arousal group, or the player's own Allow intimacy choice.
- Close and intimate actions are never offered while a child is in the conversation.
- The stock Inventory and Attack actions can be limited to followers.
- Settings page: one Living World tab with Status, Characters, Memory and Settings sub-tabs. Memory can be filtered (talked with, custom NPCs, followers) and the delete section is smaller.
- Module map: a module with an update on Nexus is drawn in its own blue colour, and the map refreshes by itself every few seconds, so the AI model box turns green as soon as a reply comes back.

### Fixed
- In a group talk, someone joining late dropped everyone who was already there, including a child, so close or intimate actions could be offered with a child present.
- A talk started a few seconds after another one lost all its speakers, so a friend could not be offered a hug.
- The debug menu's "What they can do now" unloaded the shared NPC file.
- The Status page said loading a save was enough for game data to show; it now says to talk to an NPC first.
- The Save player description button was too narrow for its text.
- "Asked before" tracking rewritten, plus smaller fixes found in play testing.

## 1.1.7 (2026-11-04)
- Fixes a crash at the end of setup in Skyrim VR.
- Now requires powerofthree's Papyrus Extender: install it first.
- Living World Main Status names required mods that are missing.

## 1.1.6 (2026-11-03)
- The setup summary no longer scans the whole save, a possible cause of a crash when setup finishes.
- MCM: new Overview page with the settings and module checks; Module status page removed; pages fill top to bottom; the opening screen says to pick a page.
- Update Arousal to 1.0.1 too so rated NPCs appear.

## 1.1.5 (2026-10-31)
- Living World Setup power: does what the hotkey does. Cast it at an NPC to set their temperament, or at nobody to run the setup. For controllers and hotkey clashes.
- MCM toggle: Setup power in magic menu (on by default).
- The setup reminder and the setup result ask you to save the game, since the setup and temperaments live in the save.
- Troubleshooting report shows the real version.

## 1.1.4 (2026-10-30)
- The example memories in the Memory tab use Player instead of a character name.

## 1.1.3 (2026-10-30)
- Update check runs every 3 days by default (set the days in the settings tab; 0 turns it off).
- Updates are listed under What needs attention in their own colour; the module map shows status only.
- New player presets that describe only your character: Traveller (default), Sellsword, Quiet stranger, Scholar. Fame, Dragonborn status and guild ranks come from World and Knowledge instead.

## 1.1.2 (2026-10-30)
- Update check: the Hub asks Nexus whether an installed Living World module has a newer version and shows it on Living World Main Status. Only the mods' Nexus IDs are sent.
- New module map: Skyrim, Mantella, Direct AI Connect and the AI model on the left, the Hub in the middle, one arm per module on the right. Hover a box for the reason behind its colour.
- The AI model box turns green once a reply comes back this session.

## 1.0.0 (2026-10-26)
- First release.
