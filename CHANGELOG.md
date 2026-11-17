# Changelog

Every change to Mantella Living World - Integration Hub. The Nexus page lists only the main changes for each version.

## Unreleased

### New
- Status page: when Mantella cannot make lip sync files (FonixData.cdf or FaceFXWrapper.exe missing, and no Creation Kit LipGenerator), "What needs attention" says which file is missing and where it goes. Lip sync stays optional and nothing is downloaded or copied. Settings, Updates and notices: "Hide the lip sync notice" (off by default) leaves the line out.

### Fixed
- With World: buying from a merchant by talking is fixed. On trade talk the merchant now gets his whole ware list with shop prices when it fits (up to 100 wares), and a ware you name is told with its count and price, so a ware he has is sold with the Trade action instead of opening the barter menu. The day's trade recap at the start of a talk no longer reads as gold or goods handed over in this talk.
- Menu dialogue: an unreadable acknowledgement file is left as it is (with a warning in the log) instead of being replaced by one NPC's mark, which lost every other NPC's marks.
- Speed testing: the voice stage is timed for every voice service, Direct AI Connect's XTTS included, not only for services that keep Mantella's base method.

### Changed
- Mantella's log (debug level) gets one trade check line per request: whether it was trade talk, whether the wares line was sent, and whether the Trade action was offered.

## 1.2.3 (2026-11-15)

### New
- Memories that always matter: being intimate with you, you fighting against them, you saving them (or them saving you) in a fight, fighting at your side, a death they saw or heard from family, a promise (and one you broke), marrying, getting engaged or parting with you, joining or leaving you as a follower, gold you gave them (500 or more, or a quarter of what they carried), being caught stealing from them, learning that the hooded stranger was you, and how you first met are marked from what the game recorded, not left to the summary's judgement. They are kept longer, stay in the list of memories instead of being folded into the older summary (at most 8 per NPC; older ones of the same kind merge into one line with how many times and the days), and count towards an earlier update of the Now paragraph.
- Mod facts: what other mods record about an NPC and you (for example how far a Shadowman's NPCs story has gone) becomes a short background line for that NPC, read from the game when they join a talk. Fact files per plugin in StorageUtilData\MantellaLivingWorld\modfacts\ (user, shipped, generated); files for Gerdur and Sigrid come with the Hub, and tools\modfacts_generate.py drafts files for your other plugins from their own dialogue. Shown read-only on the NPCs page. Player page: Scan my dialogue mods writes those files for you (it finds your Mod Organizer 2 folder by itself where it can, or takes your Data folder), shows a table of what it found, and never touches your own or the shipped files.
- NPCs page: one page per NPC. Pick a save and an NPC (type to search) and see, in the order the model reads it: the prompt preview (the exact text last sent, or a rebuild, and which it is), Personality (bio, versions, voice, Optimize with AI, and the short bio beside the original), Background, Now, the facts history, Memories, Commands and Knows about. A one-line summary under the picker shows who they are, their partner, follower status, absolute commands and intimacy choice. A red line shows where Now, a custom line or a belief says something about that NPC that the game does not (married, home, follower, faction).
- Prompt order: each NPC's part of the prompt now comes as personality (their bio), background facts, how things are now, memories, absolute commands. One rule line tells the model that where they differ, the later part is the current truth.
- Now: one short paragraph per NPC, their situation as they believe it. It replaces How they have changed (an existing note becomes the first Now). It is rewritten after a talk, never during one: every few talks, and after a talk where something changed (a custom event, a game fact such as marriage, home, follower or faction, or an absolute command given, lifted or released). What is no longer true drops out. Edit, lock, reset or ask for a rewrite on the NPCs page; switch it off under Settings, Custom events and Now paragraphs.
- Facts history, per save: every background fact is dated with what caused it (first seen, the game, you, a custom event, a command). A fact that is replaced is kept on hold and comes back when its cause ends. Several partners at once are kept, and a relationship is stored once, so both NPCs agree. Marriage (M.A.R.A.S when installed, else the vanilla marriage; NFF's elope is its own line), home, follower, role and factions are read from the game at every talk; race and sex once. A value you type over them is what the NPC believes and never changes the game. Your own lines can be added, ended and hidden from the NPC; the game's are read-only.
- Background also has a religion line (temple and priest factions, else your own), a values line (what they care about and will not do; yours, or a short one written once from the bio) and feelings toward groups where the factions make them clear (a Stormcloak hates the Legion and the Thalmor, a guard sides with whoever holds their hold). Ordinary Nords and village folk dislike the Thalmor unless a membership says otherwise. With Relationships: an NPC's own spouse from the game shows up, with their family; when they marry you that spouse stays ("Alvor, whom Sigrid left to marry you").
- Flags the mod obeys (NPCs page, Background): Intimacy: always willing, Intimacy: never (nothing overrides it, not even an absolute command), Always close to the player, Trades without asking (for World's trading) and Ignores Absolute Commands. A child is never close or intimate, whatever is ticked.
- Intimacy setting (Settings page and the MCM's Overview page, kept in step): NPC decides (default) or Lovers only (as before). With NPC decides every adult is offered the scene and says yes or no as the person they are, from what they have to go on (how they stand with you, their partner, how long they have known you, an absolute command). A no shows on screen, is told back to them and is remembered. Always willing NPCs say yes in either setting; Intimacy: never NPCs are never offered it. The Yes/No box before a scene stays. Children never get anything, and nothing intimate is offered to anyone in a talk until the game has confirmed that everyone in it is an adult.
- Release an absolute command from the Living World hotkey's menu on that NPC (Release command) or from the NPCs page, with three choices: they remember it and know it was a spell (memories from that time are marked "while under your spell"), they forget the whole time (they notice a gap: "has no memory of day 3, and it frightens her"), or they keep believing. It takes effect from the next reply, also in a talk going on. Release ends what the command made true and brings back what it replaced. When a marriage was made under the command, Relationships can ask once whether to end it.
- Forgetting one thing is clean by default: they simply do not remember it. A command that wipes a whole period leaves a gap they notice; a command that says they never notice forgets cleanly. A forgotten memory also leaves the short summary of their older memories. Every forget and release is written to the Hub's own record of what really happened (never sent to the NPC), shown on the NPCs page.
- Delete: one memory can be removed for good from the NPCs page (you only; commands never delete). A backup file is kept and the record notes it.
- World news: one log per save of weddings, divorces, deaths, big fights, killings, spells that came to light and notable events you type. It reaches the people who were there at once, their family and household about a day later, the rest of the town as rumours after a few days, and the whole hold after about a week if it was big. Each NPC learns it when they next talk, as seen, told by someone, or a rumour. People who only share a name or a look (guards, bandits) are never mixed up. What happens between two people is never passed on, quiet wipes and releases are not gossip, and children never hear of weddings or anything intimate.
- With World: murders and attacks you commit, and deaths of named people, are news too, also while the fight is still going on. Witnesses know what they saw at their next talk, and a killing they saw a short while ago is on their mind already in the greeting. A killer in a hood is "a hooded stranger" to anyone who does not know you, a child who saw it is never named, and your followers do not spread it.
- Knows about (NPCs page): what each NPC knows, how they heard it and since when, who else knows an event, and buttons to make them forget it or tell them.
- Absolute Commands can name who forgets: "and everyone in Riverwood", "everyone who was there", "her brother". Absent NPCs forget too. Removing the command, or releasing it as a spell they know of, gives it all back.
- People who know someone well notice when that person is under your spell. Skilled mages can tell it is Illusion magic, and who cast it.
- What a hold has come to believe about you (killings, spells that came to light, several marriages) colours how its people talk to you. Only what reached them counts, never something they were made to forget.
- Memories say how the NPC knows them: what they saw is plain; what they were told ("Lucan told you: ..."), rumours and their own thoughts are marked as such.
- Mood: how an NPC feels at the end of a talk carries into the next one and fades back to their usual self over a few game days.
- Fights are remembered by how much they mattered: a dragon or a named foe longer than a wolf, and longer still when someone on their side died, when they or you nearly died, or when you saved them.
- Story arcs: memories of one ongoing story (a courtship, a feud, a journey, a time under a spell) are linked. When one comes back to mind, a one-line summary of the whole story comes with it. No extra request.
- Loading an earlier save sets aside the memories, world news and Now paragraphs made after it (not deleted); they come back if you load the newer save again. Once you play on from the earlier save, the set-aside ones count as another timeline and stay kept.
- A custom event can change how others see an NPC (an illusion over their clothes): other NPCs in the talk, or a talk about them, get that note.
- Short bios: each long bio (Mantella's or your own override) is rewritten once into one short shape for everyone (Personality, Looks, Voice, History, Knows, Sample lines, Rules), leaving out the race and sex the Background already states, and sent instead of the original from the next talk. The bio's roleplay rules ("should" and "do not" lines, "never assumed" lines, lines under Rules, Roleplay, Continuity or Starting point, gates such as "until she believes you are the Dragonborn", and the sentence a rule points back to) are copied into the Rules part word for word, and family and spouse ties ("the mother of Serana") are always kept with the name. Every result is checked without another request: no name or number may be lost, nothing new may be named, quoted lines must be in the bio (plurals, quote style and capitals aside), a reason the bio gives for a fact must stay, and it must be clearly shorter. It is asked again once, else the original is kept and the reason shown. When a later update changes the checks, stored short bios are checked again and written again only if they no longer pass; until a current one exists the original bio is sent. One request per NPC after a talk (at most three NPCs a talk), never during one. Your bios and override files are never changed by this. Settings: Short bios (on by default). Player page: Optimise all my overrides now (with a summary) and Write short bios into my override files (backs them up first). NPCs page: the original and the short version side by side, Use original for this NPC and Optimise again.
- Action notifications (MCM, Overview page, on by default): a short line on screen when a Living World action runs or is refused; the NPCs in the talk are told what happened too.
- With World: when you talk about buying, selling, gold or gifts, one short line says what each NPC here carries; a merchant gets a few wares of each kind across prices, how many more there are by kind, and that the list is not complete, so he offers to check instead of saying he has none. Debts from a deal are kept as promises ("Lucan owes you 50 gold for the sword").
- Status page: the last prompt by section (the bio sent and the original, Background, Now, world, memories, commands, rules and the whole system prompt).
- Rule lines: what someone wears is their own choice unless a gift or an event says you gave it, and you are never blamed for looking; NPCs speak of events as something they lived or know, never "the event says".
- Console (experimental, off by default, no key by default; MCM): during a Mantella conversation, type what should become real in the game ("give me 2000 gold"), the console commands are written for you, and a box lists every command; nothing runs unless you pick Run. Needs ConsoleUtilSSE NG and the next Mantella - Direct AI Connect.
- Mod facts: Use scanned mod facts (experimental, off by default) on the Settings page. Your own fact files and the ones that come with the Hub are always used; files written by Scan my dialogue mods only while it is on.
- Mod facts: Show the last scan result shows the finished scan's table, also after a restart.
- Speed testing (Settings page, off by default): stage times for how long a talk takes to start, written by the game (talk key, each module's work when an NPC joins, start request sent) and by Mantella's side (request received, prompt built, first model token, first sentence, voice audio, lip file, line handed to the game, tokens), joined by a talk number; and Prepare NPC data ahead, which fills an NPC's file when you aim at them so a talk start only refreshes what changes from moment to moment. Both switch without a restart.

### Changed
- The Living World tab's pages are now Status, NPCs, Player, Events, World Knowledge (with Knowledge installed) and Settings. Everything about one NPC is on the NPCs page; the old Characters and Memory pages are gone. Player has your description, Apply now, Reset ALL overrides and the short-bio buttons. Events has custom events, the commands in force in a save with their settings, and deleting every NPC's memories in a save. Other modules can add a page to the tab.
- Living World pages are calmer and easier to read: plain field titles, one button size, buttons that delete or reset things outlined in red and set apart at the end of their row, one style for status boxes and warnings, and tables that no longer squash or overflow.
- Fewer actions sent on every reply: World's trading is one Trade action, Followers' orders are two (FollowerOrder and PartyOrder), Survival's EatThis is part of ShareFood, and the descriptions are shorter. With OStim Expansion, change position and rate favourite positions are offered only while that NPC is in an OStim scene (with an older OStim Expansion, as before).
- The Living World hotkey's Allow intimacy is now called Always willing.
- Absolute Command overrides every limit except Intimacy: never and the child checks: while a command is in force for an NPC they count as close and intimate, so the actions it asks for (an OStim scene, for example) are offered and can start. On Mantella's side it ends as soon as the command is removed or wears off; in the game it lasts the Commands last setting, or one game day when that is 0.
- A command to forget one thing no longer hides a whole memory: each memory it fits is rewritten without that part (one short summary request per memory) and the original is hidden. Unhide, or removing the command, brings the original back. It covers every memory of that thing, and hides only memories that clearly fit (a looser fit only when one short request confirms it; names alone no longer count as a match).
- A custom event never changes marriage, home, follower status or faction membership; it is noted on the NPCs page as not matching the game instead.
- A preset of an NPC keeps their bio and Background together (older presets still load their bio). Export and import take each NPC's Background and flags along.
- Menu dialogue memories report only what the lines say, each exchange on its own and in order, with the scene that followed it; no act, reason or feeling is added that no line or scene states.
- A short talk is summarised in full when it holds a gift, a theft, a promise, an intimate moment, follows dialogue or a scene from before the talk, or when you ask about your relationship. Other short talks keep your last line and the NPC's last reply.
- Scan my dialogue mods skips lines with no words of the mod's own, settings and switches (SMP, voice, combat, speaking, timers, debug, MCM), follower framework factions and framework plugins (OStim, SexLab, follower frameworks), and never quotes an explicit line from any mod. Quotes end at a sentence end (at most 120 characters), never inside a word.

### Fixed
- A memory could be saved as raw text with brackets and quotes when the summary reply was cut off; the complete part is now read, and a memory already saved that way is shown and used as plain text.
- With World: what an NPC said with you in the game's own dialogue (Mantella running or not) becomes her memory at her next talk, however many days later: one memory per day it happened, dated, before she says a word. Talk from a mod whose scripts start scenes is kept as an important memory and updates her Now paragraph. A store that fills up while Mantella runs is summarised in the background. A scene from OStim Expansion that ended before any talk becomes her memory at once.
- With World: an NPC who picked up an item during a talk still knows how much gold she carries.
- Custom events stay true: one reaches the NPC as something that already happened, no gift menu or trade action opens for it on the next reply, and a gift menu or offer that came to nothing no longer makes the NPC (or their memories) say it never happened. Gold, marriage, home and follower status are still only real when the game says so.
- Taking back a custom event (undo or the Events page) also takes the NPC's reply to it out of the talk and out of its memory. Undo right after a trim mid-talk also hides the memory the trim wrote. Undo at the start of a new talk no longer takes back the last talk's event.
- Recognition: an NPC knows whether they recognise you under a hood already in the greeting. Someone who knows you well (a follower, your spouse, someone under your spell, someone you have talked with several times) always recognises you, and a command given during a talk corrects the greeting. Talks with you in a hood, and news about you, no longer count as knowing you: memories, feelings and the Now paragraph of a hooded meeting say "a hooded stranger", never your name, until they learn who you are.
- First meeting: the greeting waits at most a second, only for the game's age check on a newly met NPC (if it never comes, nothing adult is offered); a value the game writes later counts as its safe one (not in a scene, not close). An NPC met before gets no wait at all.
- A follower's outfit change is one short line saying what they newly put on, instead of dozens of equip, unequip and drop lines, whatever the name's case; a weapon they draw keeps its own line.
- Your own world, crime and fight files were left out after loading a save as if they belonged to another character.
- The home line names the town ("Hod and Gerdur's House, in Riverwood"), never the hold as if it were a town.
- A prompt rule that is too long is no longer cut in the middle of a sentence: only whole rule lines are sent.
- Command and release lines can no longer be taken for a speaker's name (an NPC once said nothing at all).
- Timed absolute commands no longer wear off at once after loading an earlier save, or because of a command queued in another save. A command whose check was cut off (Mantella closed during it) is read again instead of staying "checking".
- Forget commands no longer hide more older memories after every talk; they only look at the talk just saved.
- Memory: a broken archive file is closed at once; a memory hidden while a talk was being saved no longer loses that talk; a hidden memory no longer comes back through repeated normal-menu dialogue, and its promises leave the prompt with it; a fight is remembered once, and saving it no longer cuts the oldest memories; the spell mark stays on a memory after it folds into the older memories; hidden memories keep their place in the list; memories never end on a cut-off event line; old-memory search stays fast with very large archives.
- The memory search model logs each loading step and is started again if a load never finishes.
- Status page: Tokens and cost and the Prompt preview show this session's replies when the page is opened or reloaded (Refresh after talking); each row holds the numbers of its own reply, and money shows to 4 decimals.
- The Living World pages no longer hang on "Loading..." for minutes: the Status page has no self-refreshing parts any more, and a value that cannot be read shows a short note instead of stopping the page.
- Fight accounts (with World) never tell a follower or your own summon that your magic was an attack on them.
- The Intimacy setting stays in step between the MCM and Mantella's Settings page both ways.
- Action arguments reach the game in the type each action declares: a number sent as text crashed the game (seen with Trade, count 0).
- An NPC whose purse changed during a talk is told the newest amount, not the one from the start of the talk.
- With OStim Expansion: an NPC the scene action is not offered to (Lovers only and not your lover, or Intimacy: never) is told so as a game fact, so they no longer agree to a scene that cannot start.
- The Absolute Command help in the MCM points to the NPCs page and the hotkey's menu for releasing a command.
- The Console no longer freezes Mantella while it writes the commands (with the next Mantella - Direct AI Connect).
- Status page: "Setup not run" now says what to do: run the setup with the Living World hotkey (nobody targeted), then save your game. Setup lives in the save, so loading a save made before it shows this again.
- An NPC asked to rate their appetite (Arousal) or favourite positions (OStim Expansion) no longer speaks the rating as their line ("I'll rate her appetite silently and hand over the gold."). The request is no longer an event in the scene: it goes with that one reply as a note for the action only, and the reply answers what you said. A new rule line: a reply never announces actions in place of dialogue.
- With World: a merchant no longer refuses a ware only because it was not among the few named to him: the list is a sample, he sells what you ask for with the Trade action, and the game refuses it if it is really not in stock. After his barter menu opened (it restocks his chest) or a sale, he is told his stock has changed and still tries the sale.
- With World: fight accounts no longer say you fought or killed when you never attacked (an aura or cloak of yours touched the enemy). Needs the new World.
- With World: an NPC whose purse changed during a talk is told so as a plain fact; the old wording was once spoken back as reasoning about her ("She just picked up 100 gold, so she can cover thirty").
- The log notes when a rating request is sent as an action note ("Living World: rating request for ... sent as an action note").
- Short bios: a rule sentence that starts by pointing back ("To such a person ...") now keeps the sentence it points to, and a line on how someone reacts in a situation ("If approached at the Thalmor Embassy: I'm surprised to see you") is kept with the situation. Stored short bios are written again.
- Short bios: a short bio may no longer add {player_name} where the bio says "the player", state as fact what the bio gives only as a rumour, or list a word from someone's spoken line as their insult. Stored short bios that fail these checks are written again.
- Menu dialogue Mantella already showed in a talk is no longer made into a second memory at the next talk.
- Menu dialogue and scene memories use the same day numbers as talk memories (a talk the same day no longer reads as yesterday).
- Scenes from before a talk are remembered in the NPC's own words with their game day and hour, not with a fixed "less than an hour ago".
- Mod fact lines are in the first talk with an NPC, not only from the second.
- A gift was counted twice (600 gold saved as 1200). A gift is always in the memory, and kept as long as other gifts, also after a short talk.
- An NPC who does not recognise you under a hood sees "the hooded stranger" in menu dialogue, its stored dialogue, scene memories and mod fact lines, never your name. An NPC who has been intimate with you recognises you, hood or not.
- Scenes from before a talk reach the memories again: they come with the talk's second message, and are then added to the memory of the dialogue that led to them, or saved as their own memory.
- The game's own dialogue keeps your words where the game did not record your topic but Mantella's own copy of the same dialogue has them.
- Memories and Now paragraphs are written in the NPC's own words ("I") and keep no "less than an hour ago": the day and hour are stored, how long ago is worked out when shown.
- Only the earliest memory of you is marked as how you met (the memory of the game's own dialogue or a scene counts).
- A short small talk keeps what you said, without the event lines in brackets.
- An NPC who does not recognise you under a hood never sees your name: "the hooded stranger" also in the hood line itself.
- A Now paragraph is no longer written from a memory of a loaded-away later save.
- A death counts as close only when the dead was family, household, someone they work with, or a fellow follower; a stranger dying nearby is ordinary news.
- A scene from before a talk is no longer lost when that talk ends early (for example when the voice server is down): OStim Expansion sends it again at the next talk until it is in a memory, and it is never stored twice.
- The greeting already knows the game's own dialogue from before the talk (its memory is made before the prompt).
- A scene sent again that is already in her memory is no longer shown to the NPC a second time.
- Scenes in a memory read as the NPC's own words: "CHAD climaxed twice and I climaxed once." instead of the game's list.
- Talk start does less: a module asking for an NPC's file to be updated rewrites only the fields that change, the mod facts are read once per join, and events are registered again only on older saves.
- Prepare NPC data ahead (speed testing) prepares only an NPC you keep aiming at for a moment, close by, and never while that NPC is joining a talk.
- A talk's number is no longer closed by a late "talk ended" from the talk before it.
- The Living World hotkeys follow the MCM after each loading screen and when the MCM closes, instead of a check every 10 seconds.

## 1.2.2 (2026-11-14)

### New
- The All in One download has its own update check: Status shows one line when a newer All in One is on Nexus.
- With World: fight accounts for each NPC who fought near you, in the newest message while World keeps them, and one memory entry for a fight worth remembering. Three new settings on the MCM's World page.
- Memory keeps every memory: older ones still fold into the short "earlier" note, but each stays whole in a per-NPC archive (`<NPC> - <ref id>.archive.sqlite` next to the memory file). The first load of an old memory file copies it to `upgrade_backup` first.
- Each memory is rated in the same summary request (importance, emotion, type, tags). Small talk fades within days, important memories over months, open promises never; when the budget is tight the strongest memories stay.
- Older memories come back when a talk is about them: by meaning with a small local search model (all-MiniLM-L6-v2, 23 MB, downloaded once with a checksum check, run on the CPU), by keywords without it.
- Hidden memories: a memory can be taken out of an NPC's mind without deleting it. The Memory page lists hidden ones greyed out with an Unhide button.
- Stock barks and normal-menu lines heard over and over no longer fill memory.
- Optional follower diary (off by default): one short diary memory per game day, one extra summary request a day.
- Four new memory settings: Bring back older memories, Download the memory search model, Leave out chatter, Follower diary.
- Custom events (Mantella's Add Custom Game Event hotkey, N by default) are listed per save and NPC on the Memory page, where each can be edited or taken back. In a talk that is still going on the change applies from the next reply and goes into its memory; a memory already written from it is hidden (Unhide brings it back) and rewritten without the event, or with the edit, in one short request per NPC.
- Silent custom events: start one with `silent:` and everyone present knows it happened and remembers it, but nobody answers it. A new setting makes every custom event silent; `react:` then makes one narrated. Type `undo` as a custom event to take back your last one in this talk.
- How NPCs have changed: a short note after each NPC's bio, written from their memories every few talks (sooner after something important), in one summary request. Their bio and your character overrides are never changed. The Memory page shows the note to edit, lock or reset; two new settings turn it off or set how often it is written.
- Absolute Command: a new hotkey (G by default, MCM Overview page) opens a text box during a Mantella conversation. What you type ("I cast a spell that makes you forget the robbery", "You will follow me and obey without question") binds every NPC in the talk above every rule, their personality, relationship and memories, and they answer it at once without you speaking. It stays with each NPC until you remove it on the Memory page, or for the hours it names. A command to forget something hides the memories that fit it (nothing is deleted); removing the command or its hours running out brings them back. The NPC does not know anything was done to them unless the command says so. Never works on children, and it does not unlock actions the action gates hide. Three new settings on the Memory page: how long commands last, whether one short summary request reads each command, and how many memories one command can hide.

### Changed
- With the next Mantella - Direct AI Connect update, on Anthropic (Native, cached): a third cache point after the Living World rules, so the action list and rules are read from the cache when you start talking to another NPC with the same actions within 5 minutes, instead of being written again. Older Direct AI Connect versions use the two cache points as before.

## 1.2.1 (2026-11-09)

### New
- Survival is on the module map and in "What each module does".

## 1.2.0 (2026-11-09)

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
