from django.core.management.base import BaseCommand
from accounts.models import Company
from rewards.services.probabilities import ensure_wheels_for_company

class Command(BaseCommand):
    help = "Initialise (ou ré-initialise) les roues de probabilités pour chaque entreprise."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Ré-initialise les roues (réécrit le pool et remet idx=0)."
        )

    def handle(self, *args, **options):
        reset = options["reset"]
        count = 0
        for company in Company.objects.all():
            ensure_wheels_for_company(company)
            count += 1
        self.stdout.write(self.style.SUCCESS(
            f"Roues initialisées pour {count} entreprise(s)."
        ))
        if reset:
            # Optionnel : si tu veux forcer un reset plus fort, tu peux
            # étendre ensure_wheels_for_company pour régénérer les pools
            self.stdout.write(self.style.WARNING(
                "Option --reset indiquée : assure-toi que ensure_wheels_for_company "
                "régénère les pools comme attendu."
            ))
