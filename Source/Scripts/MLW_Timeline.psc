Scriptname MLW_Timeline Hidden
{Mantella Living World - Integration Hub: this save's talk counter, so that NPC memories follow the save that is
loaded. It lives in StorageUtil (the SKSE co-save), so it rolls back when an older save is loaded, and is written into
conversation.json for the Living World extension in Mantella:

talk_seq: this talk's number in this save's line while a talk runs, else the next talk's number. talk_id: a random id
of the running talk ("" between talks). talk_parent: the id of the last talk that ended in this save's line.
talk_open: 1 while a talk runs. talk_time: the game time the running talk started.

Call TalkStarted once per Mantella talk (MantellaConversation_Started), TalkEnded when it ends
(MantellaConversation_Ended), and Write whenever conversation.json is written, before JsonUtil.Save. The Ended event
does not always arrive: the next TalkStarted first closes a talk that is still open.}

; Opens a new talk (closing one left open) and writes the counter into asFile.
Function TalkStarted(string asFile) global
	If StorageUtil.GetIntValue(None, "MLW_TalkOpen", 0) == 1
		Close()
	EndIf
	int seq = StorageUtil.GetIntValue(None, "MLW_TalkSeq", 1)
	string id = seq + "-" + Utility.RandomInt(0, 2147483646) + "-" + ((Utility.GetCurrentRealTime() * 1000.0) as int)
	StorageUtil.SetStringValue(None, "MLW_TalkId", id)
	StorageUtil.SetIntValue(None, "MLW_TalkOpen", 1)
	StorageUtil.SetFloatValue(None, "MLW_TalkTime", Utility.GetCurrentGameTime())
	Write(asFile)
	JsonUtil.Save(asFile)
EndFunction

; Closes the running talk (if any) and writes the counter into asFile.
Function TalkEnded(string asFile) global
	; an Ended that arrives after the next talk has started (it can come late) belongs to the earlier talk: Mantella
	; empties the talk before it sends Ended, so a talk with people in it is the new one, and stays open
	MantellaConversation talk = Game.GetFormFromFile(0x03D41A, "Mantella.esp") as MantellaConversation
	bool newTalk = talk && talk.IsRunning() && talk.CountActorsInConversation() > 0
	If StorageUtil.GetIntValue(None, "MLW_TalkOpen", 0) == 1 && !newTalk
		Close()
	EndIf
	Write(asFile)
	JsonUtil.Save(asFile)
EndFunction

; The running talk becomes the last one that ended; the next talk gets the next number.
Function Close() global
	StorageUtil.SetStringValue(None, "MLW_TalkLast", StorageUtil.GetStringValue(None, "MLW_TalkId", ""))
	StorageUtil.SetIntValue(None, "MLW_TalkSeq", StorageUtil.GetIntValue(None, "MLW_TalkSeq", 1) + 1)
	StorageUtil.SetStringValue(None, "MLW_TalkId", "")
	StorageUtil.SetIntValue(None, "MLW_TalkOpen", 0)
EndFunction

; Puts the counter into asFile (a JsonUtil file); the caller saves it.
Function Write(string asFile) global
	int isOpen = StorageUtil.GetIntValue(None, "MLW_TalkOpen", 0)
	JsonUtil.SetIntValue(asFile, "talk_seq", StorageUtil.GetIntValue(None, "MLW_TalkSeq", 1))
	If isOpen == 1
		JsonUtil.SetStringValue(asFile, "talk_id", StorageUtil.GetStringValue(None, "MLW_TalkId", ""))
	Else
		JsonUtil.SetStringValue(asFile, "talk_id", "")
	EndIf
	JsonUtil.SetStringValue(asFile, "talk_parent", StorageUtil.GetStringValue(None, "MLW_TalkLast", ""))
	JsonUtil.SetIntValue(asFile, "talk_open", isOpen)
	JsonUtil.SetFloatValue(asFile, "talk_time", StorageUtil.GetFloatValue(None, "MLW_TalkTime", -1.0))
EndFunction
