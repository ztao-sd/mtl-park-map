from fastapi import APIRouter

from mtl_park_map.app.parking_spot_analyzer import PaidParkingAnalyzer

# Setup
parking_sign_analyzer = ParkingSignAnalyzer()
parking_spot_analyzer = PaidParkingAnalyzer()



api_router = APIRouter()

@api_router.get("/parking-signs")
def get_parking_signs():
    pass

@api_router.get("/paid-spots")
def get_paid_spots():
    pass

@api_router.get("/address-location")
def get_address_location():
    pass
