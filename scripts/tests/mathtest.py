
taco: tuple[int, int] = (1, 2)
floaty: tuple = (1.0, 2.0)

print(type(taco), type(tuple[int, int]))
print(f"{ isinstance(floaty, tuple)}")