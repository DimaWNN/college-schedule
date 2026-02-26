from aiogram.fsm.state import State, StatesGroup

class ReplaceState(StatesGroup):
    choose_date = State()
    enter_text  = State()

class CreateGroupState(StatesGroup):
    enter_name = State()

class TransferLeaderState(StatesGroup):
    choose_member = State()
