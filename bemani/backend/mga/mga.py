# vim: set fileencoding=utf-8
import base64
import random
from typing import List

from bemani.backend.mga.base import MetalGearArcadeBase
from bemani.backend.ess import EventLogHandler
from bemani.common import Profile, VersionConstants, Time
from bemani.data import UserID
from bemani.protocol import Node


class MetalGearArcade(
    EventLogHandler,
    MetalGearArcadeBase,
):
    name: str = "Metal Gear Arcade"
    version: int = VersionConstants.MGA

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

    def handle_playerdata_usergamedata_scorerank_request(self, request: Node) -> Node:
        # Not sure what this should do, looked like a thing to look up global rank
        # but it doesn't always send the player's ID, so possibly useless?
        #
        # The request looks like this:
        # <playerdata method="usergamedata_scorerank">
        #     <data>
        #         <eaid __type="str"></eaid>
        #         <gamekind __type="str">I36</gamekind>
        #         <vkey __type="str"></vkey>
        #         <conditionkey __type="str">HISTATTR</conditionkey>
        #         <score __type="s64">-1</score>
        #     </data>
        # </playerdata>
        root = Node.void("playerdata")
        root.add_child(Node.s32("result", 1))

        rank = Node.void("rank")
        root.add_child(rank)
        rank.add_child(Node.s32("rank", -1))
        rank.add_child(Node.u64("updatetime", Time.now() * 1000))
        return root

    def handle_matching_request_request(self, request: Node) -> Node:
        refid = request.child_value("data/eaid")
        userid = self.data.remote.user.from_refid(self.game, self.version, refid)

        root = Node.void("matching")

        if userid is None:
            root.add_child(Node.s32("result", -1))
            return root

        matchgrp = request.child_value("data/matchgrp")
        waituser = request.child_value("data/waituser")
        waittime = request.child_value("data/waittime")

        joinip = request.child_value("data/joinip")
        joinport = request.child_value("data/joinport")
        localip = request.child_value("data/localip")
        localport = request.child_value("data/localport")

        # Save connection info
        self.data.local.lobby.put_play_session_info(
            self.game,
            self.version,
            userid,
            {
                "joinip": joinip,
                "joinport": joinport,
                "localip": localip,
                "localport": localport,
                "pcbid": self.config.machine.pcbid,
                "time": Time.now(),
            },
        )

        # Look for compatible existing session
        sessions = self.data.local.lobby.get_all_lobbies(
            self.game,
            self.version,
            max_age=waittime,
        )

        for host_uid, lobby in sessions:
            if (
                lobby.get_int("matchgrp") == matchgrp
                and not lobby.get_bool("finalized")
                and len(lobby["participants"]) < lobby.get_int("waituser")
            ):
                # Join existing
                participants = set(lobby["participants"])
                participants.add(userid)
                lobby["participants"] = list(participants)
                self.data.local.lobby.put_lobby(
                    self.game, self.version, host_uid, lobby
                )

                host_info = self.data.local.lobby.get_play_session_info(
                    self.game,
                    self.version,
                    host_uid,
                )

                root.add_child(Node.s32("result", 1))  # guest
                root.add_child(Node.s64("hostid", lobby.get_int("id")))
                root.add_child(Node.string("hostip_g", host_info.get_str("joinip")))
                root.add_child(Node.s32("hostport_g", host_info.get_int("joinport")))
                root.add_child(Node.string("hostip_l", host_info.get_str("localip")))
                root.add_child(Node.s32("hostport_l", host_info.get_int("localport")))
                return root

        # No session found ? create new host session
        hostid = Time.now()  # stable 64-bit unique value

        self.data.local.lobby.put_lobby(
            self.game,
            self.version,
            userid,
            {
                "id": hostid,
                "matchgrp": matchgrp,
                "waituser": waituser,
                "waittime": waittime,
                "createtime": Time.now(),
                "participants": [userid],
                "finalized": False,
            },
        )

        root.add_child(Node.s32("result", 0))  # host
        root.add_child(Node.s64("hostid", hostid))
        root.add_child(Node.string("hostip_g", joinip))
        root.add_child(Node.s32("hostport_g", joinport))
        root.add_child(Node.string("hostip_l", localip))
        root.add_child(Node.s32("hostport_l", localport))
        return root

    def handle_matching_wait_request(self, request: Node) -> Node:
        hostid = request.child_value("data/hostid")

        root = Node.void("matching")

        sessions = self.data.local.lobby.get_all_lobbies(self.game, self.version)
        session = None
        host_uid = None

        for uid, lobby in sessions:
            if lobby.get_int("id") == hostid:
                session = lobby
                host_uid = uid
                break

        if session is None:
            root.add_child(Node.s32("result", -1))
            return root

        elapsed = Time.now() - session.get_int("createtime")
        time_left = max(session.get_int("waittime") - elapsed, 0)

        participants = session["participants"]

        # If full or timer expired ? start match
        if len(participants) >= session.get_int("waituser") or time_left == 0:
            root.add_child(Node.s32("result", len(participants)))

            matchlist = Node.void("matchlist")
            root.add_child(matchlist)

            count = 0
            for uid in participants[:8]:
                info = self.data.local.lobby.get_play_session_info(
                    self.game,
                    self.version,
                    uid,
                )
                if not info:
                    continue

                record = Node.void("record")
                record.add_child(Node.string("pcbid", info.get_str("pcbid")))
                record.add_child(Node.string("statusflg", "0"))
                record.add_child(Node.s32("matchgrp", session.get_int("matchgrp")))
                record.add_child(Node.s64("hostid", hostid))
                record.add_child(Node.u64("jointime", info.get_int("time") * 1000))
                record.add_child(Node.string("connip_g", info.get_str("joinip")))
                record.add_child(Node.s32("connport_g", info.get_int("joinport")))
                record.add_child(Node.string("connip_l", info.get_str("localip")))
                record.add_child(Node.s32("connport_l", info.get_int("localport")))

                matchlist.add_child(record)
                count += 1

            matchlist.add_child(Node.u32("record_num", count))
            return root

        # Not ready yet
        root.add_child(Node.s32("result", 0))
        root.add_child(Node.s32("prwtime", time_left))
        return root

    def handle_matching_finish_request(self, request: Node) -> Node:
        hostid = request.child_value("data/hostid")

        root = Node.void("matching")

        sessions = self.data.local.lobby.get_all_lobbies(self.game, self.version)

        for uid, lobby in sessions:
            if lobby.get_int("id") == hostid:
                lobby["finalized"] = True
                self.data.local.lobby.put_lobby(self.game, self.version, uid, lobby)
                break

        root.add_child(Node.s32("result", 0))
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
