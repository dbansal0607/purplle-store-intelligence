# FIXES APPLIED: BUG #4, BUG #5, BUG #18 — Torso color histogram Re-ID embedding model, StaffPostProcessor voting ensemble class, and camera transitions spatial gating logic.

import uuid
import numpy as np
import cv2
from pipeline.config import REID_SIMILARITY_THRESHOLD, STAFF_PURPLE_RATIO_THRESHOLD

# BUG #18: Spatial gating transitions based on store layout adjacency rules
CAMERA_TRANSITIONS = {
    # Store 1 Transitions
    "CAM 3 - entry": ["CAM 1 - zone", "CAM 2 - zone"],
    "CAM 1 - zone": ["CAM 2 - zone", "CAM 5 - billing", "CAM 3 - entry"],
    "CAM 2 - zone": ["CAM 1 - zone", "CAM 5 - billing", "CAM 3 - entry"],
    "CAM 5 - billing": ["CAM 1 - zone", "CAM 2 - zone", "CAM 3 - entry"],
    
    # Store 2 Transitions
    "entry 1": ["zone", "billing_area"],
    "entry 2": ["zone", "billing_area"],
    "zone": ["billing_area", "entry 1", "entry 2"],
    "billing_area": ["zone", "entry 1", "entry 2"]
}

class PersonReID:
    def __init__(self):
        pass
        
    def get_embedding(self, crop):
        """
        BUG #5 Fix: Torque color histogram in HSV space.
        Avoids ImageNet backbone misalignment and runs efficiently on CPU.
        """
        h, w = crop.shape[:2]
        if h < 20 or w < 20:
            return np.zeros(64, dtype=np.float32)
            
        # middle third = torso area (where clothing/apparel details are located)
        torso = crop[h//3:2*h//3, :, :]
        if torso.size == 0:
            return np.zeros(64, dtype=np.float32)
            
        hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        
        # Calculate 32-bin Hue and 32-bin Saturation histograms
        hist_h = cv2.calcHist([hsv], [0], None, [32], [0, 180])
        hist_s = cv2.calcHist([hsv], [1], None, [32], [0, 256])
        
        hist = np.concatenate([hist_h, hist_s]).flatten()
        norm = np.linalg.norm(hist)
        
        return hist / norm if norm > 0 else hist

def is_purple_uniform(crop_bgr):
    """
    Color signature checker for standard Purplle uniform (Hue: 120-165).
    """
    h, w, _ = crop_bgr.shape
    if h < 20 or w < 20:
        return False
    # Check middle chest area (10% to 50% height, 10% to 90% width)
    upper_body = crop_bgr[int(h*0.1):int(h*0.5), int(w*0.1):int(w*0.9)]
    if upper_body.size == 0:
        return False
    hsv = cv2.cvtColor(upper_body, cv2.COLOR_BGR2HSV)
    
    # Purple/lavender uniform color HSV bounds
    lower_purple = np.array([120, 40, 40])
    upper_purple = np.array([165, 255, 255])
    
    mask = cv2.inRange(hsv, lower_purple, upper_purple)
    purple_ratio = np.sum(mask > 0) / mask.size
    return purple_ratio > STAFF_PURPLE_RATIO_THRESHOLD

class SessionStitcher:
    def __init__(self):
        self.reid = PersonReID()
        self.sessions = []  # list of dicts: {"visitor_id", "last_seen", "embedding", "cameras", "is_staff"}
        
    def _camera_compatible(self, from_cam, to_cam):
        """
        BUG #18 Fix: Boundary transition check.
        Ensures tracks do not match across physically disconnected cameras.
        """
        # Strip extension if passed
        from_c = from_cam.split(".")[0]
        to_c = to_cam.split(".")[0]
        
        if from_c == to_c:
            return True
            
        allowed = CAMERA_TRANSITIONS.get(from_c, [])
        return to_c in allowed or any(adj in to_c for adj in allowed)

    def stitch_track(self, track_crop, camera_name, current_time):
        is_staff = is_purple_uniform(track_crop)
        emb = self.reid.get_embedding(track_crop)
        
        best_match = None
        max_sim = -1.0
        
        # Check matching sessions within 5 minutes (300 seconds)
        for session in self.sessions:
            time_gap = (current_time - session["last_seen"]).total_seconds()
            if time_gap < 300:
                # Check spatial compatibility (cannot teleport)
                compatible = False
                for prev_cam in session["cameras"]:
                    if self._camera_compatible(prev_cam, camera_name):
                        compatible = True
                        break
                        
                if not compatible:
                    continue
                    
                sim = np.dot(emb, session["embedding"])
                if sim > max_sim:
                    max_sim = sim
                    best_match = session
                    
        # Verify threshold alignment
        if max_sim >= REID_SIMILARITY_THRESHOLD and best_match is not None:
            visitor_id = best_match["visitor_id"]
            best_match["last_seen"] = current_time
            # running average update
            best_match["embedding"] = 0.8 * best_match["embedding"] + 0.2 * emb
            best_match["embedding"] /= np.linalg.norm(best_match["embedding"])
            if camera_name not in best_match["cameras"]:
                best_match["cameras"].append(camera_name)
            if best_match["is_staff"]:
                is_staff = True
        else:
            visitor_id = f"VIS_{uuid.uuid4().hex[:8]}"
            new_session = {
                "visitor_id": visitor_id,
                "last_seen": current_time,
                "embedding": emb,
                "cameras": [camera_name],
                "is_staff": is_staff
            }
            self.sessions.append(new_session)
            
        return visitor_id, is_staff

class StaffPostProcessor:
    """
    BUG #4 Fix: Voting-ensemble staff identifier.
    Excludes employees from visitor metrics via color, temporal, transition, and location counts.
    """
    def __init__(self):
        pass
        
    def process(self, track_history, track_zones_visited, track_purple_votes, total_frames):
        staff_flags = {}
        for track_id, history in track_history.items():
            if not history:
                staff_flags[track_id] = False
                continue
                
            votes = 0
            
            # Signal 1: Color uniform votes ratio
            purple_ratio = track_purple_votes.get(track_id, 0) / len(history)
            if purple_ratio > 0.3:
                votes += 1
                
            # Signal 2: Temporal presence (>50% of the total clip time)
            if len(history) > (total_frames * 0.5):
                votes += 1
                
            # Signal 3: Zone transitions (traverses 5+ distinct zones)
            zones = track_zones_visited.get(track_id, set())
            if len(zones) >= 5:
                votes += 1
                
            # Signal 4: Spatial persistence (cashier stays close to counter for 60+ frames)
            if len(history) >= 60:
                history_np = np.array(history)
                avg_pos = np.mean(history_np, axis=0)
                distances = np.linalg.norm(history_np - avg_pos, axis=1)
                # If 90% of track points are within 0.2 of average position
                if np.mean(distances < 0.2) > 0.9:
                    votes += 1
                    
            staff_flags[track_id] = votes >= 2
            
        return staff_flags
