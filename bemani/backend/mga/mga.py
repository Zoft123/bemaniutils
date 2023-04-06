# vim: set fileencoding=utf-8
import base64
from typing import List, Dict, Optional, Tuple, Any
import time
from bemani.backend.mga.base import MetalGearArcadeBase
from bemani.backend.ess import EventLogHandler
from bemani.common import Profile, VersionConstants, Time
from bemani.data import UserID
from bemani.protocol import Node


class MatchingSession:
    def __init__(
        self,
        host_id: int,
        join_ip: str,
        join_port: int,
        local_ip: str,
        local_port: int,
        request_data: Node,
        timestamp: float,
    ):
        self.host_id = host_id
        self.join_ip = join_ip
        self.join_port = join_port
        self.local_ip = local_ip
        self.local_port = local_port
        self.request_data = request_data
        self.timestamp = timestamp


class MetalGearArcade(
    EventLogHandler,
    MetalGearArcadeBase,
):
    name: str = "Metal Gear Arcade"
    version: int = VersionConstants.MGA
    active_sessions: List[MatchingSession] = []

    def __update_shop_name(self, profiledata: bytes) -> None:
        # Figure out the profile type
        csvs = profiledata.split(b",")
        if len(csvs) < 2:
            # Not long enough to care about
            return
        datatype = csvs[1].decode("ascii")
        if datatype != "PLAYDATA":
            # Not the right profile type requested
            return
        # Grab the shop name
        try:
            shopname = csvs[30].decode("shift-jis")
        except Exception:
            return
        self.update_machine_name(shopname)

    def handle_matching_request_request(self, request: Node) -> Node:
        joinip = request.child_value("data/joinip")
        joinport = request.child_value("data/joinport")
        localip = request.child_value("data/localip")
        localport = request.child_value("data/localport")
        matchgrp = request.child_value("data/matchgrp")

        request_data = {
            "joinip": joinip,
            "joinport": joinport,
            "localip": localip,
            "localport": localport,
            "matchgrp": matchgrp,
        }

        matching_session, is_new_session = self.find_matching_session_or_create(
            request_data
        )

        response = Node.void("response")
        response.set_attribute("status", "0")
        matching = Node.void("matching")
        response.add_child(matching)
        matching.add_child(Node.s64("hostid", matching_session.host_id))
        matching.add_child(Node.s32("result", 0 if is_new_session else 1))
        matching.add_child(Node.string("hostip_g", matching_session.join_ip))
        matching.add_child(Node.string("hostip_l", matching_session.local_ip))
        matching.add_child(Node.s32("hostport_l", matching_session.local_port))
        matching.add_child(Node.s32("hostport_g", matching_session.join_port))

        return matching

    def find_matching_session_or_create(
        self, request_data: Dict
    ) -> Tuple[MatchingSession, bool]:
        matching_session = self.find_matching_session(request_data)

        if matching_session is None:
            host_id = 1  # Generate a unique host ID
            new_session = MatchingSession(
                host_id,
                request_data["joinip"],
                request_data["joinport"],
                request_data["localip"],
                request_data["localport"],
                request_data,
                time.time(),
            )
            self.active_sessions.append(new_session)
            matching_session = new_session
            is_new_session = True
            print(f"Created new session: {new_session.request_data}")
        else:
            is_new_session = False
        return matching_session, is_new_session

    def find_matching_session(
        self, request_data: Dict, hostid: Optional[int] = None
    ) -> Optional[MatchingSession]:
        for session in self.active_sessions:
            print(
                f"Searching for hostid: {hostid}, checking session with hostid: {session.host_id}"
            )
            if hostid is not None:
                print(f"Checking session: {session.request_data}")
                if session.host_id == hostid:
                    print(f"Found matching session: {session.request_data}")
                    return session
                elif session.request_data["matchgrp"] == request_data["matchgrp"]:
                    print("No matching session found")
                    return session
        return None

    def handle_matching_wait_request(self, request: Node) -> Node:
        hostid = request.child_value("data/hostid")
        print(f"Active sessions: {self.active_sessions}")
        matching_session = self.find_matching_session(request_data=None, hostid=hostid)
        remaining_time = 0

        if matching_session is not None:
            elapsed_time = time.time() - matching_session.timestamp
            remaining_time = max(60 - elapsed_time, 0)
            print(remaining_time)
            print(time.time())
            print(matching_session.timestamp)

            if elapsed_time >= 60:
                result = 1
            else:
                result = 0
        else:
            result = 1
        response = Node.void("response")
        response.set_attribute("status", "0")
        matching = Node.void("matching")
        response.add_child(matching)
        matching.add_child(Node.s32("result", result))
        matching.add_child(Node.s32("prwtime", int(remaining_time)))

        return matching

    def handle_system_getmaster_request(self, request: Node) -> Node:
        # See if we can grab the request
        data = request.child("data")
        if not data:
            root = Node.void("system")
            root.add_child(Node.s32("result", 0))
            return root
        # Figure out what type of messsage this is
        reqtype = data.child_value("datatype")
        reqkey = data.child_value("datakey")

        # System message
        root = Node.void("system")

        if reqtype == "S_SRVMSG" and reqkey == "INFO":
            # Generate system message
            settings1_str = "2011081000:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1:1"
            settings2_str = "1,1,1,1,1,1,1,1,1,1,1,1,1,1"

            # Send it to the client, making sure to inform the client that it was valid.
            root.add_child(
                Node.string(
                    "strdata1",
                    base64.b64encode(settings1_str.encode("ascii")).decode("ascii"),
                )
            )
            root.add_child(
                Node.string(
                    "strdata2",
                    base64.b64encode(settings2_str.encode("ascii")).decode("ascii"),
                )
            )
            root.add_child(Node.u64("updatedate", Time.now() * 1000))
            root.add_child(Node.s32("result", 1))
        else:
            # Unknown message.
            root.add_child(Node.s32("result", 0))
        return root

    def handle_playerdata_usergamedata_send_request(self, request: Node) -> Node:
        # Look up user by refid
        refid = request.child_value("data/eaid")
        userid = self.data.remote.user.from_refid(self.game, self.version, refid)
        if userid is None:
            root = Node.void("playerdata")
            root.add_child(
                Node.s32("result", 1)
            )  # Unclear if this is the right thing to do here.
            return root
        # Extract new profile info from old profile
        oldprofile = self.get_profile(userid)
        is_new = False
        if oldprofile is None:
            oldprofile = Profile(self.game, self.version, refid, 0)
            is_new = True
        newprofile = self.unformat_profile(userid, request, oldprofile, is_new)

        # Write new profile
        self.put_profile(userid, newprofile)

        # Return success!
        root = Node.void("playerdata")
        root.add_child(Node.s32("result", 0))
        return root

    def handle_playerdata_usergamedata_recv_request(self, request: Node) -> Node:
        # Look up user by refid
        refid = request.child_value("data/eaid")
        profiletypes = request.child_value("data/recv_csv").split(",")
        profile = None
        userid = None
        if refid is not None:
            userid = self.data.remote.user.from_refid(self.game, self.version, refid)
        if userid is not None:
            profile = self.get_profile(userid)
        if profile is not None:
            return self.format_profile(userid, profiletypes, profile)
        else:
            root = Node.void("playerdata")
            root.add_child(
                Node.s32("result", 1)
            )  # Unclear if this is the right thing to do here.
            return root

    def format_profile(
        self, userid: UserID, profiletypes: List[str], profile: Profile
    ) -> Node:
        root = Node.void("playerdata")
        root.add_child(Node.s32("result", 0))
        player = Node.void("player")
        root.add_child(player)
        records = 0
        record = Node.void("record")
        player.add_child(record)

        for profiletype in profiletypes:
            if profiletype == "3fffffffff":
                continue
            for j in range(len(profile["strdatas"])):
                strdata = profile["strdatas"][j]
                bindata = profile["bindatas"][j]

                # Figure out the profile type
                csvs = strdata.split(b",")
                if len(csvs) < 2:
                    # Not long enough to care about
                    continue
                datatype = csvs[1].decode("ascii")
                if datatype != profiletype:
                    # Not the right profile type requested
                    continue
                # This is a valid profile node for this type, lets return only the profile values
                strdata = b",".join(csvs[2:])
                d = Node.string("d", base64.b64encode(strdata).decode("ascii"))
                record.add_child(d)
                d.add_child(
                    Node.string("bin1", base64.b64encode(bindata).decode("ascii"))
                )

                # Remember that we had this record
                records = records + 1
        player.add_child(Node.u32("record_num", records))
        return root

    def unformat_profile(
        self, userid: UserID, request: Node, oldprofile: Profile, is_new: bool
    ) -> Profile:
        # Profile save request, data values are base64 encoded.
        # d is a CSV, and bin1 is binary data.
        newprofile = oldprofile.clone()
        strdatas: List[bytes] = []
        bindatas: List[bytes] = []

        record = request.child("data/record")
        for node in record.children:
            if node.name != "d":
                continue
            profile = base64.b64decode(node.value)
            # Update the shop name if this is a new profile, since we know it came
            # from this cabinet. This is the only source of truth for what the
            # cabinet shop name is set to.
            if is_new:
                self.__update_shop_name(profile)
            strdatas.append(profile)
            bindatas.append(base64.b64decode(node.child_value("bin1")))
        newprofile["strdatas"] = strdatas
        newprofile["bindatas"] = bindatas

        # Keep track of play statistics across all versions
        self.update_play_statistics(userid)

        return newprofile
