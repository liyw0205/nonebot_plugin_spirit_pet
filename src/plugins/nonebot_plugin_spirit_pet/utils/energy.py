from ..domain.state import Pet


def restore_energy(pet: Pet, now: int, interval: int) -> None:
    restored = max(0, now - pet.energy_updated) // interval
    pet.energy = min(100, pet.energy + restored)
    if pet.energy == 100:
        pet.energy_updated = max(now, pet.energy_updated)
    else:
        pet.energy_updated += restored * interval


def add_energy(pet: Pet, amount: int, now: int) -> int:
    gain = min(amount, 100 - pet.energy)
    pet.energy += gain
    if pet.energy == 100:
        pet.energy_updated = max(now, pet.energy_updated)
    return gain
