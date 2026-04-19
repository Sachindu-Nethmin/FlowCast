from difflib import SequenceMatcher

def test_similarity(t, text_l):
    ratio = SequenceMatcher(None, t.lower().strip(), text_l.lower().strip()).ratio()
    
    t_words = t.lower().split()
    text_words = text_l.lower().split()
    if len(t_words) > 1 and len(text_words) > 1:
        # If the first words are completely different (0 matches), penalize heavily
        if SequenceMatcher(None, t_words[0], text_words[0]).ratio() < 0.4:
            ratio *= 0.8
            
    print(f"'{t}' vs '{text_l}' -> {ratio:.2f}")
    return ratio

print("Testing Healer Diagnosis Logic (FIXED):")
t = "HTTP Service"
m1 = "MCP Service"
m2 = "HTTP Service"
m3 = "Rest Service"

r1 = test_similarity(t, m1)
r2 = test_similarity(t, m2)
r3 = test_similarity(t, m3)

threshold = 0.82
print(f"\nThreshold: {threshold}")
print(f"Auto-correct HTTP -> MCP? {'YES' if r1 >= threshold else 'NO'}")
print(f"Auto-correct HTTP -> HTTP? {'YES' if r2 >= threshold else 'NO'}")
print(f"Auto-correct HTTP -> Rest? {'YES' if r3 >= threshold else 'NO'}")
