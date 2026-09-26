"""ADK session storage with full event JSON and replayable state deltas.

Events are the durable source of truth. The snapshot is a cache: replaying the
event journal repairs a crash between inserting an event and updating a snapshot.
The controller serializes writers using a renewable MongoDB lease.
"""
import time
from uuid import uuid4

from google.adk.events import Event
from google.adk.sessions import BaseSessionService, Session
from google.adk.sessions.base_session_service import ListSessionsResponse
from pymongo import ReturnDocument


class MongoSessionService(BaseSessionService):
    def __init__(self, db):
        self.db = db

    @staticmethod
    def key(app_name, user_id, session_id):
        return dict(app_name=app_name, user_id=user_id, session_id=session_id)

    async def create_session(self, *, app_name, user_id, state=None, session_id=None):
        key = self.key(app_name, user_id, session_id or str(uuid4()))
        initial = {k: v for k, v in (state or {}).items() if not k.startswith("temp:")}
        now = time.time()
        await self.db.adk_sessions.insert_one({**key, "initial_state": initial,
            "state": initial, "created_at": now, "updated_at": now,
            "last_event_seq": 0, "schema_version": 1})
        return await self.get_session(**key)

    async def get_session(self, *, app_name, user_id, session_id, config=None):
        key = self.key(app_name, user_id, session_id)
        doc = await self.db.adk_sessions.find_one(key)
        if not doc:
            return None
        state = dict(doc["initial_state"])
        records = await self.db.adk_events.find(key).sort("seq", 1).to_list(None)
        events = [Event.model_validate(r["event_json"]) for r in records]
        for event in events:
            if event.actions:
                state.update(event.actions.state_delta)
        # User/app scopes are shared across sessions; temp scope never leaves RAM.
        scope_docs = await self.db.adk_scopes.find({"app_name": app_name,
            "$or": [{"user_id": user_id}, {"user_id": "__app__"}]}).to_list(None)
        for scope in scope_docs:
            prefix = "app:" if scope["user_id"] == "__app__" else "user:"
            state.update({prefix + k: v for k, v in scope.get("state", {}).items()})
        state = {k: v for k, v in state.items() if not k.startswith("temp:")}
        last_update = max([doc["updated_at"], *(e.timestamp for e in events)])
        if config:
            if config.after_timestamp is not None:
                events = [e for e in events if e.timestamp > config.after_timestamp]
            if config.num_recent_events is not None:
                events = events[-config.num_recent_events:] if config.num_recent_events else []
        return Session(id=session_id, app_name=app_name, user_id=user_id,
                       state=state, events=events, last_update_time=last_update)

    async def list_sessions(self, *, app_name, user_id=None):
        query = {"app_name": app_name}
        if user_id is not None:
            query["user_id"] = user_id
        docs = await self.db.adk_sessions.find(query).sort("updated_at", 1).to_list(None)
        sessions = []
        for doc in docs:
            session = await self.get_session(**self.key(app_name, doc["user_id"], doc["session_id"]))
            session.events = []
            sessions.append(session)
        return ListSessionsResponse(sessions=sessions)

    async def delete_session(self, *, app_name, user_id, session_id):
        key = self.key(app_name, user_id, session_id)
        await self.db.adk_events.delete_many(key)
        await self.db.adk_sessions.delete_one(key)

    async def get_user_state(self, *, app_name, user_id):
        doc = await self.db.adk_scopes.find_one({"app_name": app_name, "user_id": user_id})
        return doc.get("state", {}) if doc else {}

    async def append_event(self, session, event):
        if event.partial:
            return event
        key = self.key(session.app_name, session.user_id, session.id)
        prior = await self.db.adk_events.find_one({**key, "event_id": event.id})
        if prior:
            return Event.model_validate(prior["event_json"])
        self._apply_temp_state(session, event)
        event = self._trim_temp_delta_state(event.model_copy(deep=True))
        doc = await self.db.adk_sessions.find_one_and_update(key,
            {"$inc": {"last_event_seq": 1}}, return_document=ReturnDocument.AFTER)
        if not doc:
            raise ValueError("Cannot append to a missing session")
        await self.db.adk_events.insert_one({**key, "seq": doc["last_event_seq"],
            "event_id": event.id, "invocation_id": event.invocation_id,
            "event_json": event.model_dump(mode="json", exclude_none=True), "timestamp": event.timestamp})
        self._commit_event_to_session(session, event)
        for prefix, scope_user in [("app:", "__app__"), ("user:", session.user_id)]:
            delta = {"state." + k[len(prefix):]: v for k, v in event.actions.state_delta.items() if k.startswith(prefix)}
            if delta:
                await self.db.adk_scopes.update_one({"app_name": session.app_name, "user_id": scope_user},
                                                   {"$set": delta}, upsert=True)
        session.last_update_time = event.timestamp
        await self.db.adk_sessions.update_one(key, {"$set": {
            "state": {k: v for k, v in session.state.items() if not k.startswith("temp:")},
            "updated_at": event.timestamp, "last_invocation_id": event.invocation_id}})
        return event
