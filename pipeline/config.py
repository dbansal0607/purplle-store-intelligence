# WARNING: The zone polygons below are visual approximations and placeholder boundaries.
# For production deployment, they MUST be calibrated against actual camera coordinates.
# You can run: python pipeline/calibrate_zones.py --video "Store 1/CAM 1 - zone.mp4"
# and adjust these coordinates from the output.

import numpy as np

# Camera mapping configuration
CAMERA_CONFIG = {
    # Store 1 Configurations
    "CAM 3 - entry.mp4": {
        "store_id": "STORE_BLR_001",
        "camera_type": "ENTRY",
        "entry_line": [(0.2, 0.8), (0.8, 0.8)], # Line to cross for entry/exit
        "entry_direction": -1, # Cross direction vector sign
        "zones": {}
    },
    "CAM 1 - zone.mp4": {
        "store_id": "STORE_BLR_001",
        "camera_type": "ZONE",
        "zones": {
            "SKINCARE": [(0.05, 0.1), (0.45, 0.1), (0.45, 0.9), (0.05, 0.9)],
            "HAIRCARE": [(0.5, 0.1), (0.95, 0.1), (0.95, 0.9), (0.5, 0.9)]
        }
    },
    "CAM 2 - zone.mp4": {
        "store_id": "STORE_BLR_001",
        "camera_type": "ZONE",
        "zones": {
            "COSMETICS": [(0.05, 0.1), (0.45, 0.1), (0.45, 0.9), (0.05, 0.9)],
            "FRAGRANCE": [(0.5, 0.1), (0.95, 0.1), (0.95, 0.9), (0.5, 0.9)]
        }
    },
    "CAM 5 - billing.mp4": {
        "store_id": "STORE_BLR_001",
        "camera_type": "BILLING",
        "zones": {
            "BILLING": [(0.2, 0.2), (0.8, 0.2), (0.8, 0.95), (0.2, 0.95)]
        }
    },
    
    # Store 2 Configurations
    "entry 1.mp4": {
        "store_id": "STORE_BLR_002",
        "camera_type": "ENTRY",
        "entry_line": [(0.1, 0.75), (0.9, 0.75)],
        "entry_direction": -1,
        "zones": {}
    },
    "entry 2.mp4": {
        "store_id": "STORE_BLR_002",
        "camera_type": "ENTRY",
        "entry_line": [(0.1, 0.75), (0.9, 0.75)],
        "entry_direction": -1,
        "zones": {}
    },
    "zone.mp4": {
        "store_id": "STORE_BLR_002",
        "camera_type": "ZONE",
        "zones": {
            "COSMETICS": [(0.05, 0.15), (0.48, 0.15), (0.48, 0.85), (0.05, 0.85)],
            "SKINCARE": [(0.52, 0.15), (0.95, 0.15), (0.95, 0.85), (0.52, 0.85)]
        }
    },
    "billing_area.mp4": {
        "store_id": "STORE_BLR_002",
        "camera_type": "BILLING",
        "zones": {
            "BILLING": [(0.25, 0.25), (0.75, 0.25), (0.75, 0.9), (0.25, 0.9)]
        }
    }
}

# Tracking parameters
CONFIDENCE_THRESHOLD = 0.25
TRACK_IOU_THRESHOLD = 0.5
REID_SIMILARITY_THRESHOLD = 0.80
STAFF_PURPLE_RATIO_THRESHOLD = 0.08
FRAME_SKIP = 3  # Process every 3rd frame for speed

def is_point_in_polygon(point, polygon_coords, img_w, img_h):
    """
    Checks if a point (x, y) is inside a polygon defined by list of normalized tuples (x, y).
    """
    import cv2
    poly_pts = np.array([[pt[0] * img_w, pt[1] * img_h] for pt in polygon_coords], dtype=np.int32)
    result = cv2.pointPolygonTest(poly_pts, (point[0], point[1]), False)
    return result >= 0
