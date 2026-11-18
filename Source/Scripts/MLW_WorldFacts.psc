Scriptname MLW_WorldFacts Hidden
{Mantella Living World - Integration Hub: a few more facts about an NPC and the player for Mantella's side, written
into the same channel files MLW_Channel writes (PapyrusUtil JSON under StorageUtilData/MantellaLivingWorld/).

npc/<base id>.json: illusion (the NPC's Illusion skill, without fortify effects), magic (1 when they have magic
training: a College of Winterhold member, Illusion 25 or more, or another school 50 or more), town (the town or city
they are in now) and home_town (the town or city of their editor location), "" when not in one.
conversation.json: player_illusion (the player's Illusion skill, without fortify effects).

Towns come from the location's own keywords (LocTypeCity, LocTypeTown, LocTypeSettlement), walking up through parent
locations with powerofthree's Papyrus Extender. Global functions only: call them from MLW_Channel.}

Function WriteNpc(Actor akNpc, string asPath) global
	If !akNpc || asPath == ""
		Return
	EndIf
	int illusion = akNpc.GetBaseActorValue("Illusion") as int
	JsonUtil.SetIntValue(asPath, "illusion", illusion)
	JsonUtil.SetIntValue(asPath, "magic", MagicTrained(akNpc, illusion) as int)
	JsonUtil.SetStringValue(asPath, "town", TownOf(akNpc.GetCurrentLocation()))
	JsonUtil.SetStringValue(asPath, "home_town", TownOf(akNpc.GetEditorLocation()))
EndFunction

Function WritePlayer(string asConversation) global
	Actor player = Game.GetPlayer()
	If player && asConversation != ""
		JsonUtil.SetIntValue(asConversation, "player_illusion", player.GetBaseActorValue("Illusion") as int)
	EndIf
EndFunction

bool Function MagicTrained(Actor akNpc, int aiIllusion) global
	If aiIllusion >= 25
		Return true
	EndIf
	Faction college = Game.GetFormFromFile(0x01F259, "Skyrim.esm") as Faction  ; CollegeofWinterholdFaction
	If college && akNpc.IsInFaction(college)
		Return true
	EndIf
	Return akNpc.GetBaseActorValue("Destruction") >= 50 || akNpc.GetBaseActorValue("Conjuration") >= 50 \
		|| akNpc.GetBaseActorValue("Alteration") >= 50 || akNpc.GetBaseActorValue("Restoration") >= 50
EndFunction

; The town or city a location is in: the location itself or the nearest parent with a town keyword; "" when none.
string Function TownOf(Location akLocation) global
	Keyword city = Keyword.GetKeyword("LocTypeCity")
	Keyword town = Keyword.GetKeyword("LocTypeTown")
	Keyword settlement = Keyword.GetKeyword("LocTypeSettlement")
	Location here = akLocation
	int depth = 0
	While here && depth < 8
		If (city && here.HasKeyword(city)) || (town && here.HasKeyword(town)) || (settlement && here.HasKeyword(settlement))
			Return here.GetName()
		EndIf
		here = PO3_SKSEFunctions.GetParentLocation(here)
		depth += 1
	EndWhile
	Return ""
EndFunction
