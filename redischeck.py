import os
import django
from channels.layers import get_channel_layer

# Set the default settings module for Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

# Initialize Django
django.setup()

# Now you can use Django features
channel_layer = get_channel_layer()
print(channel_layer)
