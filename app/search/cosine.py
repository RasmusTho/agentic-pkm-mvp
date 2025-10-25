import math

def dot(a, b):
    return sum(x * y for x, y in zip(a, b))

def norm(a):
    return math.sqrt(sum(x * x for x in a)) or 1.0

def cosine(a, b):
    return dot(a, b) / (norm(a) * norm(b))
