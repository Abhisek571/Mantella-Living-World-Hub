Scriptname MLW_MCM extends MCM_ConfigBase
{The hub's MCM Helper menu. Buttons call the functions here.}

Function WriteReport()
	MLW_Hub hub = Game.GetFormFromFile(0x000820, "Mantella Living World - Integration Hub.esp") as MLW_Hub
	If hub
		hub.WriteReport()
	EndIf
EndFunction
