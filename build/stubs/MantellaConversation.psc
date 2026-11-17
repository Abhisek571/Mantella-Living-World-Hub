Scriptname MantellaConversation extends Quest
{Compile stub: what the hub's report reads. The real script binds at runtime.}
int Function CountActorsInConversation()
EndFunction
Actor Function GetActorInConversationByIndex(int indexOfActor)
EndFunction
Function RemoveActorsFromConversation(Actor[] actorsToRemove)
EndFunction
bool Function IsPlayerInConversation()
EndFunction
; the Absolute Command hotkey (MLW_Command): an in-game event and an event-only NPC turn
bool Function GetIsTalking()
EndFunction
Function AddIngameEvent(string eventText)
EndFunction
Function AddExtraRequestAction(string extraAction)
EndFunction
Function RequestContinueConversation(bool updateInGameEvents = false)
EndFunction
