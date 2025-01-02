from typing import Dict, List, Optional, Any

class Endpoint:
    def __init__(self, name: str, required_params: Optional[List[str]] = None, optional_params: Optional[List[str]] = None, xor_params: Optional[List[str]] = None):
        self.name = name
        self.required_params = required_params or []
        self.optional_params = optional_params or []
        self.xor_params = xor_params or []

    def validate(self, args: Dict[str, Any]) -> bool:
        """Validate required parameters and XOR conditions."""
        
        # Check required parameters
        for param in self.required_params:
            if param not in args or args[param] is None:
                return False

        # Check XOR logic (only one of xor_params can be set)
        if self.xor_params:
            xor_values = [args.get(param) is not None for param in self.xor_params]
            if sum(xor_values) != 1:  # Exactly one must be true
                return False

        return True

# Define endpoints
endpoints = {
    'stations': Endpoint(
        name='stations',
        optional_params=['format', 'lang']
    ),
    'liveboard': Endpoint(
        name='liveboard',
        xor_params=['station', 'id'],  # XOR parameters
        optional_params=['date', 'time', 'arrdep', 'alerts', 'format', 'lang']
    ),
    'connections': Endpoint(
        name='connections',
        required_params=['from', 'to'],
        optional_params=['date', 'time', 'timesel', 'typeOfTransport', 'alerts', 'results', 'format', 'lang']
    ),
    'vehicle': Endpoint(
        name='vehicle',
        required_params=['id'],
        optional_params=['date', 'alerts', 'format', 'lang']
    ),
    'composition': Endpoint(
        name='composition',
        required_params=['id'],
        optional_params=['data', 'format', 'lang']
    ),
    'disturbances': Endpoint(
        name='disturbances',
        optional_params=['lineBreakCharacter', 'format', 'lang']
    )
}
