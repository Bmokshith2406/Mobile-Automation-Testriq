from typing import Dict, Type
from app.models.cir import ActionType
from app.services.extractors.BaseExtractor import BaseExtractor
from app.services.extractors.ClickExtractor import ClickActionExtractor
from app.services.extractors.TypeExtractor import TypeActionExtractor
from app.services.extractors.SelectExtractor import SelectActionExtractor
from app.services.extractors.AssertExtractor import AssertActionExtractor
from app.services.extractors.DialogExtractor import DialogActionExtractor


class ExtractorFactory:
    """
    Registry and Factory mapping ActionType to extractor implementations.
    """

    _registry: Dict[ActionType, Type[BaseExtractor]] = {
        ActionType.click: ClickActionExtractor,
        ActionType.type: TypeActionExtractor,
        ActionType.select: SelectActionExtractor,
        ActionType.assert_action: AssertActionExtractor,
        ActionType.handle_dialog: DialogActionExtractor,
    }

    @classmethod
    def get_extractor(cls, action_type: ActionType) -> BaseExtractor:
        """
        Returns a fresh instance of the extractor registered for the action type.
        """
        extractor_cls = cls._registry.get(action_type)
        if not extractor_cls:
            raise ValueError(f"No extractor registered for action type: {action_type}")
        return extractor_cls()
