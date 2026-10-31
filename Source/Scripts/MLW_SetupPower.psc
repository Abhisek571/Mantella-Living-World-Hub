Scriptname MLW_SetupPower extends ActiveMagicEffect
{The Living World Setup power: does what the Living World hotkey does. Cast it while aiming at an NPC to set her
temperament, or at nobody to run the setup. For controllers and for players whose hotkey clashes with another mod.}

Event OnEffectStart(Actor akTarget, Actor akCaster)
	MLW_Setup setup = Game.GetFormFromFile(0x000821, "Mantella Living World - Integration Hub.esp") as MLW_Setup
	If !setup
		Debug.Notification("Mantella Living World: setup quest not found.")
		Return
	EndIf
	setup.Trigger(Game.GetCurrentCrosshairRef() as Actor)
EndEvent
