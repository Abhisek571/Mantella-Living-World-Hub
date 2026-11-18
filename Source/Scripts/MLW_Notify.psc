Scriptname MLW_Notify Hidden
{Mantella Living World - Integration Hub: what an action did, for every module. Result shows a short HUD line, unless
"Action notifications" is off in the MCM (MLW_ActionHud), and tells the NPCs in the running Mantella talk the same news
as an in-game event line, so they know whether it worked:
    MLW_Notify.Result("Gerdur gave you 50 gold", "(The 50 gold was handed over.)")
    MLW_Notify.Result("Trade declined: you have only 30 gold", "(Nothing happened: the player has only 30 gold.)")
Hud alone is for a module's own notifications, so the one switch covers them too.}

; The HUD line, when "Action notifications" is on (a missing global counts as on).
Function Hud(string asText) global
	If asText == ""
		Return
	EndIf
	GlobalVariable on = Game.GetFormFromFile(0x00080D, "Mantella Living World - Integration Hub.esp") as GlobalVariable
	If !on || on.GetValueInt() != 0
		Debug.Notification(asText)
	EndIf
EndFunction

; The HUD line and the event line for the talk; either may be "".
Function Result(string asHud, string asFact) global
	Hud(asHud)
	If asFact != ""
		int handle = ModEvent.Create("MantellaAddEvent")
		If handle
			ModEvent.PushString(handle, asFact)
			ModEvent.Send(handle)
		EndIf
	EndIf
EndFunction
