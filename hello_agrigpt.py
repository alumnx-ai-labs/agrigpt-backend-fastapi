# Test file to verify Claude Code PR review workflow
def greet_farmer(name: str) -> str:
    return f"Hello {name}, welcome to AgriGPT!"

def get_supported_crops() -> list:
    return ["wheat", "rice", "cotton", "sugarcane", "maize","Tomato"]

def calculate_fertilizer_requirements(crop: str, area: float) -> dict:
    fertilizer_requirements = {
        "wheat": {"nitrogen": 100, "phosphorus": 50, "potassium": 30},
        "rice": {"nitrogen": 120, "phosphorus": 60, "potassium": 40},
        "cotton": {"nitrogen": 80, "phosphorus": 40, "potassium": 20},
        "sugarcane": {"nitrogen": 150, "phosphorus": 70, "potassium": 50},
        "maize": {"nitrogen": 110, "phosphorus": 55, "potassium": 35},
        "Tomato":{"nitrogen":90,"phosphorus":45,"potassium":25}
    }
    
    if crop not in fertilizer_requirements:
        raise ValueError(f"Crop '{crop}' is not supported.")
    
    requirements = fertilizer_requirements[crop]
    return {nutrient: amount * area for nutrient, amount in requirements.items()}

if __name__ == "__main__":
    print(greet_farmer("John"))
    print("Supported crops:", get_supported_crops())
    print("Fertilizer requirements for wheat on 2 hectares:", calculate_fertilizer_requirements("wheat", 2))