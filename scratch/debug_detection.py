import cv2
import numpy as np
import pyautogui
from PIL import Image
from pathlib import Path

def _scale(screenshot):
    logical_w, _ = pyautogui.size()
    return screenshot.width / logical_w

def debug_detection():
    screenshot = pyautogui.screenshot()
    scale = _scale(screenshot)
    w_l = int(screenshot.width / scale)
    h_l = int(screenshot.height / scale)
    img = np.array(screenshot.resize((w_l, h_l), Image.LANCZOS))
    h, w = img.shape[:2]
    
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    
    # Greed hue range
    lower = np.array([60, 50, 50])
    upper = np.array([165, 255, 255])
    mask = cv2.inRange(hsv, lower, upper)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    print(f"Total green blobs found: {len(contours)}")
    for i, cnt in enumerate(contours):
        area = cv2.contourArea(cnt)
        if area < 4: continue
        M = cv2.moments(cnt)
        if M["m00"] == 0: continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        print(f"Blob {i}: pos=({cx}, {cy}), area={area}")

    # Test template matching for 'Run'
    icon_path = Path("kb/icons/play.png")
    if icon_path.exists():
        tmpl = cv2.imread(str(icon_path))
        # tmpl is BGR
        tmpl_gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
        screen_gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        
        best_val = -1.0
        tw, th = tmpl_gray.shape[1], tmpl_gray.shape[0]
        for s in (0.5, 0.75, 1.0, 1.25, 1.5):
            tw_s, th_s = max(1, int(tw * s)), max(1, int(th * s))
            if tw_s > screen_gray.shape[1] or th_s > screen_gray.shape[0]: continue
            tmpl_r = cv2.resize(tmpl_gray, (tw_s, th_s))
            res = cv2.matchTemplate(screen_gray, tmpl_r, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if val > best_val:
                best_val = val
                best_loc = loc
        print(f"Template match 'Run': best_val={best_val:.2f} at {best_loc if best_val > -1 else 'N/A'}")

if __name__ == "__main__":
    debug_detection()
