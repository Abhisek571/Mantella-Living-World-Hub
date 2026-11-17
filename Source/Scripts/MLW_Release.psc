Scriptname MLW_Release Hidden
{Releases an NPC from the player's absolute commands, from the Living World hotkey's menu (MLW_Setup). The player
picks what the NPC is left with: remembers it and knows it was a spell, forgets the whole time, or keeps believing.
The choice is written to SKSE/Plugins/StorageUtilData/MantellaLivingWorld/releases.json, where the Hub's side in
Mantella reads it at the next request and handles each one once (memories, the Now paragraph, the facts the command
made). A marriage made under the command is never ended here: when there is one, the Relationships module asks once.}

string Function FilePath() global
	Return "MantellaLivingWorld/releases.json"
EndFunction

; Releases kept in the file; the Hub's side remembers which ones it has read.
int Function MaxQueued() global
	Return 20
EndFunction

; Ever given an absolute command in this save (the game's own flag may already have run out while the Hub keeps the
; command until it is removed or released).
bool Function WasCommanded(Actor akNpc) global
	Return akNpc && StorageUtil.HasFloatValue(akNpc, "MLW_CommandUntil")
EndFunction

Function Ask(Actor akNpc) global
	MLW_Channel channel = Game.GetFormFromFile(0x000823, "Mantella Living World - Integration Hub.esp") as MLW_Channel
	If !akNpc || !channel
		Return
	EndIf
	string name = akNpc.GetDisplayName()
	int pick = SkyMessage.Show("Release " + name + " from your absolute commands?\n\nRemembers: " + name + " remembers that time and knows it was your spell.\nForgets: " + name + " forgets the whole time and notices a gap.\nKeeps believing: nothing changes in what " + name + " believes.\n\nThis changes what they believe, not the game.", \
			"Remembers, knows it was a spell", "Forgets the whole time", "Keeps believing", "Cancel", getIndex = true) as int
	string choice = ""
	If pick == 0
		choice = "spell"
	ElseIf pick == 1
		choice = "forget"
	ElseIf pick == 2
		choice = "believe"
	Else
		Return
	EndIf
	float now = Utility.GetCurrentGameTime()
	string path = FilePath()
	JsonUtil.StringListAdd(path, "key", (now as string) + "-" + Utility.RandomInt(0, 999999))
	JsonUtil.StringListAdd(path, "ref", channel.Hex(akNpc.GetFormID()))
	JsonUtil.StringListAdd(path, "name", name)
	JsonUtil.StringListAdd(path, "base", channel.BaseId(akNpc))
	JsonUtil.StringListAdd(path, "choice", choice)
	JsonUtil.StringListAdd(path, "time", now as string)
	JsonUtil.StringListAdd(path, "player", Game.GetPlayer().GetDisplayName())
	While JsonUtil.StringListCount(path, "key") > MaxQueued()
		JsonUtil.StringListRemoveAt(path, "key", 0)
		JsonUtil.StringListRemoveAt(path, "ref", 0)
		JsonUtil.StringListRemoveAt(path, "name", 0)
		JsonUtil.StringListRemoveAt(path, "base", 0)
		JsonUtil.StringListRemoveAt(path, "choice", 0)
		JsonUtil.StringListRemoveAt(path, "time", 0)
		JsonUtil.StringListRemoveAt(path, "player", 0)
	EndWhile
	JsonUtil.Save(path)
	StorageUtil.UnsetFloatValue(akNpc, "MLW_CommandUntil")  ; no longer close and intimate by command in the game's re-checks
	int handle = ModEvent.Create("MLW_RefreshNpc")  ; rewrites their file, also during a talk
	If handle
		ModEvent.PushForm(handle, akNpc)
		ModEvent.Send(handle)
	EndIf
	Debug.Notification(name + ": released from your commands.")
EndFunction
