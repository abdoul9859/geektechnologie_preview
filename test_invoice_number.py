#!/usr/bin/env python3
# Test script pour valider la syntaxe de _next_invoice_number

import re
from typing import Optional

def _next_invoice_number_test(db_results=None, prefix: Optional[str] = None) -> str:
    """Version de test de la fonction _next_invoice_number pour valider la syntaxe"""
    import re
    pf = (prefix or 'FAC').strip('-')
    base_prefix = f"{pf}-"

    # Stratégie 1: chercher le max parmi les numéros au format exact PREFIX-####
    last_seq = 0
    try:
        # Simulation de candidates avec des données de test
        candidates = db_results or [
            ("FAC-0042",),
            ("FAC-20250824-0001",),
            ("F20250824-0003",),
            ("FAC-20250827-0001",)
        ]
        
        # D'abord, chercher les numéros au format exact PREFIX-<digits>
        for (num,) in candidates:
            if not isinstance(num, str):
                continue
            m = re.fullmatch(rf"{re.escape(pf)}-(\d+)", num.strip())
            if m:
                val = int(m.group(1))
                if val > last_seq:
                    last_seq = val
                    print(f"Trouvé format exact: {num} -> {val}")
        
        # Si aucun trouvé au format exact, fallback : chercher le plus grand suffixe numérique
        if last_seq == 0:
            print("Aucun format exact trouvé, utilisation du fallback")
            for (num,) in candidates:
                if not isinstance(num, str):
                    continue
                # Extraire le dernier groupe de chiffres
                matches = re.findall(r'(\d+)', num.strip())
                if matches:
                    val = int(matches[-1])  # Prendre le dernier groupe de chiffres
                    if val > last_seq:
                        last_seq = val
                        print(f"Fallback: {num} -> suffixe {val}")
                        
    except Exception as e:
        print(f"Erreur dans la fonction: {e}")
        # En cas d'erreur DB, repartir de zéro proprement
        last_seq = 0

    next_seq = last_seq + 1
    print(f"Séquence suivante: {next_seq}")

    # Garantir l'unicité en cas de course (rare)
    candidate = f"{base_prefix}{next_seq:04d}"
    print(f"Numéro candidat: {candidate}")
    return candidate

if __name__ == "__main__":
    print("=== Test de la fonction _next_invoice_number ===")
    
    # Test 1: avec des numéros au format exact
    print("\nTest 1: Numéros au format exact")
    result1 = _next_invoice_number_test([("FAC-0041",), ("FAC-0042",)])
    print(f"Résultat: {result1}")
    
    # Test 2: sans numéros au format exact (fallback)
    print("\nTest 2: Fallback avec formats datés")
    result2 = _next_invoice_number_test([("FAC-20250824-0003",), ("F20250827-0005",)])
    print(f"Résultat: {result2}")
    
    # Test 3: mélange
    print("\nTest 3: Mélange de formats")
    result3 = _next_invoice_number_test([
        ("FAC-0042",), 
        ("FAC-20250824-0001",), 
        ("F20250827-0005",)
    ])
    print(f"Résultat: {result3}")
    
    print("\n=== Tests terminés ===")
