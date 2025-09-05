from django.core.management.base import BaseCommand
from accounts.models import Company
from rewards.services.probabilities import ensure_wheels

class Command(BaseCommand):
    help = "Reconstruit/initialise les roues de probabilité pour chaque entreprise."

    def handle(self, *args, **opts):
        for c in Company.objects.filter(is_active=True):
            ensure_wheels(c)
            self.stdout.write(self.style.SUCCESS(f"{c.name}: wheels ensured"))
