Scriptname MLW_ModFacts Hidden
{Mantella Living World - Integration Hub: what other mods record about an NPC and the player, read from the game.

Fact files (PapyrusUtil JSON) in StorageUtilData/MantellaLivingWorld/modfacts/: user/ (the player's own), shipped/
(come with the Hub), generated/ (written by the scanner). One file per plugin; for the same plugin user wins over
shipped and shipped over generated. A file whose plugin is not installed is ignored, and so is every NPC or form of a
plugin that is not installed: nothing is looked up there. Format: see server/living_world/mod_facts.py.

For each fact of this NPC the value is read (a global's value, a quest's stage, 0/1/2 for a quest not started /
running / completed, the NPC's faction rank or -1, the NPC's relationship rank to the player) and the first line whose
min..max holds it is written to the NPC's file as modfact_1 .. modfact_6 ("<mod>|<text>"). Read-only: nothing of the
other mod is changed. Global functions only: called from MLW_Channel.WriteNpc when an NPC joins a talk.}

string Function Root() global
	Return "MantellaLivingWorld/modfacts/"
EndFunction

int Function MaxLines() global
	Return 6
EndFunction

Function WriteNpc(Actor akNpc, string asPath) global
	If !akNpc || asPath == ""
		Return
	EndIf
	string[] lines = new string[6]
	int count = 0
	string[] done = new string[128]  ; plugins already handled by a folder that wins
	int doneCount = 0
	string[] folders = new string[3]
	folders[0] = "user/"
	folders[1] = "shipped/"
	folders[2] = "generated/"
	int last = 2
	; the switch and the scanned files are written by the server only: read from disk again, so a toggle or a rescan
	; counts from the next join instead of after a game restart
	JsonUtil.Unload(Root() + "use_generated.json", false, false)
	If JsonUtil.GetIntValue(Root() + "use_generated.json", "on", 0) != 1
		last = 1  ; scanned files only when the Hub's "Use scanned mod facts" is on (it writes that file)
	EndIf
	int f = 0
	While f <= last && count < 6
		string folder = Root() + folders[f]
		string[] files = JsonUtil.JsonInFolder(folder)
		int i = 0
		While files && i < files.Length && count < 6
			string file = folder + files[i]
			If f == 2
				JsonUtil.Unload(file, false, false)
			EndIf
			string plugin = JsonUtil.GetPathStringValue(file, ".plugin", "")
			If plugin != "" && done.Find(plugin) < 0 && Game.IsPluginInstalled(plugin)
				If doneCount < done.Length
					done[doneCount] = plugin
					doneCount += 1
				EndIf
				count = ReadFile(akNpc, file, lines, count)
			EndIf
			i += 1
		EndWhile
		f += 1
	EndWhile
	int n = 0
	While n < 6
		If n < count
			JsonUtil.SetStringValue(asPath, "modfact_" + (n + 1), lines[n])
		Else
			JsonUtil.UnsetStringValue(asPath, "modfact_" + (n + 1))
		EndIf
		n += 1
	EndWhile
EndFunction

; The lines of one file for this NPC, added to akLines from aiCount on; returns the new count.
int Function ReadFile(Actor akNpc, string asFile, string[] akLines, int aiCount) global
	string mod = JsonUtil.GetPathStringValue(asFile, ".mod", "")
	If mod == ""
		mod = JsonUtil.GetPathStringValue(asFile, ".plugin", "")
	EndIf
	int npcs = JsonUtil.PathCount(asFile, ".npcs")
	int i = 0
	While i < npcs && aiCount < 6
		string at = ".npcs[" + i + "]"
		If IsThisNpc(akNpc, JsonUtil.GetPathStringValue(asFile, at + ".npc", ""), JsonUtil.GetPathStringValue(asFile, at + ".name", ""))
			int facts = JsonUtil.PathCount(asFile, at + ".facts")
			int k = 0
			While k < facts && aiCount < 6
				string text = FactLine(akNpc, asFile, at + ".facts[" + k + "]")
				If text != ""
					akLines[aiCount] = mod + "|" + text
					aiCount += 1
				EndIf
				k += 1
			EndWhile
		EndIf
		i += 1
	EndWhile
	Return aiCount
EndFunction

; "Skyrim.esm|0x01347C": this NPC's base (or leveled base) is that form; with no reference, the name (any letter case).
bool Function IsThisNpc(Actor akNpc, string asRef, string asName) global
	If asRef != ""
		Form base = RefForm(asRef)
		Return base && (base == akNpc.GetActorBase() || base == akNpc.GetLeveledActorBase())
	EndIf
	Return asName != "" && asName == akNpc.GetDisplayName()
EndFunction

; The form a "plugin|0xID" reference names, or None (also when the plugin is not installed).
Form Function RefForm(string asRef) global
	int bar = StringUtil.Find(asRef, "|")
	If bar <= 0
		Return None
	EndIf
	string plugin = StringUtil.Substring(asRef, 0, bar)
	If !Game.IsPluginInstalled(plugin)
		Return None
	EndIf
	int id = HexToInt(StringUtil.Substring(asRef, bar + 1))
	If id <= 0
		Return None
	EndIf
	Return Game.GetFormFromFile(id, plugin)
EndFunction

; "0x000897" or "897" -> 2199; -1 when it is not hex. Letter case does not matter.
int Function HexToInt(string asText) global
	string digits = "0123456789ABCDEF"
	int start = 0
	If StringUtil.Substring(asText, 0, 2) == "0x"
		start = 2
	EndIf
	int len = StringUtil.GetLength(asText)
	If len <= start || len - start > 8
		Return -1
	EndIf
	int value = 0
	int i = start
	While i < len
		int d = StringUtil.Find(digits, StringUtil.GetNthChar(asText, i))
		If d < 0
			Return -1
		EndIf
		value = value * 16 + d
		i += 1
	EndWhile
	Return value
EndFunction

; The line of one fact for its value now, "" for none (or a form that cannot be found).
string Function FactLine(Actor akNpc, string asFile, string asAt) global
	string kind = JsonUtil.GetPathStringValue(asFile, asAt + ".kind", "")
	int value = 0
	If kind == "relationship"
		value = akNpc.GetRelationshipRank(Game.GetPlayer())
	Else
		Form target = RefForm(JsonUtil.GetPathStringValue(asFile, asAt + ".form", ""))
		If !target
			Return ""
		EndIf
		If kind == "global"
			GlobalVariable g = target as GlobalVariable
			If !g
				Return ""
			EndIf
			value = g.GetValue() as int
		ElseIf kind == "stage"
			Quest q = target as Quest
			If !q
				Return ""
			EndIf
			value = q.GetStage()
		ElseIf kind == "quest"
			Quest story = target as Quest
			If !story
				Return ""
			EndIf
			If story.IsCompleted()
				value = 2
			ElseIf story.IsRunning()
				value = 1
			EndIf
		ElseIf kind == "faction"
			Faction fac = target as Faction
			If !fac
				Return ""
			EndIf
			value = -1
			If akNpc.IsInFaction(fac)
				value = akNpc.GetFactionRank(fac)
			EndIf
		Else
			Return ""
		EndIf
	EndIf
	int lines = JsonUtil.PathCount(asFile, asAt + ".lines")
	int i = 0
	While i < lines
		string at = asAt + ".lines[" + i + "]"
		If value >= JsonUtil.GetPathIntValue(asFile, at + ".min", 1) && value <= JsonUtil.GetPathIntValue(asFile, at + ".max", 0)
			string text = JsonUtil.GetPathStringValue(asFile, at + ".text", "")
			If StringUtil.GetLength(text) > 160
				text = StringUtil.Substring(text, 0, 160)
			EndIf
			Return text
		EndIf
		i += 1
	EndWhile
	Return ""
EndFunction
