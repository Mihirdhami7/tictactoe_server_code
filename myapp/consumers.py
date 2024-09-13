import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)

room_user_count = {}
room_user_ids = {}

class BoxConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        query_string = self.scope['query_string'].decode()
        self.session_key = self.scope['session'].session_key  # Session key from the scope
        self.user_id = self.scope['url_route']['kwargs'].get('user_id')  # User ID passed in the URL

        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = self.room_name

        # Debug: Log the current user count for this room
        user_count = await self.get_user_count(self.room_group_name)
        logger.info(f"User count for room {self.room_group_name}: {user_count}")

        # Only allow a maximum of 2 users per room

        if user_count >= 2:
            # Get the new room name (incremental)
            new_room_name = await self.get_new_available_room()
            self.room_name = new_room_name
            self.room_group_name = self.room_name  # Avoid double 'game_' prefix
            
            # Add user to the new room group
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()

            logger.info(f"WebSocket connection accepted for new room: {self.room_group_name}")

            # Notify the user that they have been moved to a new room
            await self.send(text_data=json.dumps({
                'message': f'Redirected to new room: {self.room_name}',
                'session_key': self.session_key,
                'user_id': self.user_id,
            }))

        else:
            # Join the current room if it has less than 2 users
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.increment_user_count(self.room_group_name)
            await self.add_user_id(self.room_group_name, self.user_id)
            await self.accept()

            # Send the updated user count to all users in the room
            user_count = await self.get_user_count(self.room_group_name)
            
            # Broadcast the message to all users in the room
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_count_update',
                    'user_count': user_count,
                }
            )

            logger.info(f"WebSocket connection accepted for room: {self.room_group_name} with user count {user_count}")


    async def user_count_update(self, event):
    # Send the user count to the WebSocket
        await self.send(text_data=json.dumps({
            'user_count': event['user_count']
        }))


    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name, 
            self.channel_name
        )
        await self.decrement_user_count(self.room_group_name)
        await self.remove_user_id(self.room_group_name, self.user_id)
        logger.info(f"WebSocket connection closed with code: {close_code}")

    # Receive message from WebSocket
    async def receive(self, text_data):
        logger.info(f"Message received: {text_data}")
        try:
            text_data_json = json.loads(text_data)
            boxid = text_data_json.get('boxid', None)
            move = text_data_json.get('move', None)

            # Broadcast the boxid and move to the room group
            if boxid and move:
                
                if boxid == "no move" and move == "no move":
                    opponent_channel_name = await self.get_opponent_channel_name(self.room_group_name, self.channel_name)

                    if opponent_channel_name:
                        await self.channel_layer.send(
                            opponent_channel_name,
                            {
                                'boxid': 'no move',
                                'move': "no move"
                            }
                        )
                else:
                    await self.channel_layer.group_send(self.room_group_name, {
                        'type': 'box_message',
                        'boxid': boxid,
                        'move': move,
                        'user_id': self.user_id,
                    })
                    
                logger.info(f"Message broadcasted: boxid={boxid}, move={move}")
            else:
                logger.warning("Invalid message format")
        except json.JSONDecodeError:
            logger.error("Failed to decode JSON message")



    async def no_move_message(self, event):
        await self.send(text_data=json.dumps({
            'message': event['message']
        }))

    
    async def get_opponent_channel_name(self, room_group_name, current_channel_name):
        # Get the channel name of the opponent (the other user in the room)
        # Assuming you have stored the `channel_name` of both users
        all_users = await self.get_all_users_in_room(room_group_name)
        for user in all_users:
            if user != current_channel_name:
                return user
        return None
    

    async def box_message(self, event):
        boxid = event['boxid']
        move = event['move']
        user_id = event['user_id']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'boxid': boxid,
            'move': move,
            'user_id': user_id
        }))
        logger.info(f"Message sent to WebSocket: boxid={boxid}, move={move}")

    @database_sync_to_async
    def get_user_count(self, room_group_name):
        count = room_user_count.get(room_group_name, 0)
        logger.info(f"get_user_count: Room {room_group_name} has {count} users")
        return count

    @database_sync_to_async
    def increment_user_count(self, room_group_name):
        room_user_count[room_group_name] = room_user_count.get(room_group_name, 0) + 1
        logger.info(f"increment_user_count: Room {room_group_name} now has {room_user_count[room_group_name]} users")

    @database_sync_to_async
    def decrement_user_count(self, room_group_name):
        if room_group_name in room_user_count:
            room_user_count[room_group_name] -= 1
            if room_user_count[room_group_name] <= 0:
                del room_user_count[room_group_name]
            logger.info(f"decrement_user_count: Room {room_group_name} now has {room_user_count.get(room_group_name, 0)} users")

    @database_sync_to_async
    def add_user_id(self, room_group_name, user_id):
        if room_group_name not in room_user_ids:
            room_user_ids[room_group_name] = []
        room_user_ids[room_group_name].append(user_id)
        logger.info(f"add_user_id: Added user {user_id} to room {room_group_name}")

    @database_sync_to_async
    def remove_user_id(self, room_group_name, user_id):
        if room_group_name in room_user_ids:
            room_user_ids[room_group_name].remove(user_id)
            if not room_user_ids[room_group_name]:
                del room_user_ids[room_group_name]
            logger.info(f"remove_user_id: Removed user {user_id} from room {room_group_name}")

    @database_sync_to_async
    def get_all_rooms(self):
        # Returns all active room names
        return list(room_user_count.keys())
    

    @database_sync_to_async
    def get_new_available_room(self):
        existing_rooms = room_user_count.keys()  # Get all existing room names
        room_number = 1
        new_room_name = f'game_{room_number}'

        # Find an available room that has less than 2 users
        while new_room_name in existing_rooms and room_user_count.get(new_room_name, 0) >= 2:
            room_number += 1
            new_room_name = f'game_{room_number}'

        return new_room_name



