from uuid import uuid4
import numpy as np
from utils import get_manhattan_distance, logger
class PositionMixin:
    def interpretIRTable(self, lookahead_table):
        logger.info("Interpreting IR table")
        gates = []
        def _is_flat_atom(idx):
            return self.atom_type is None or self.atom_type.get(idx) == "FLAT"
        for key in lookahead_table:                 #
            lookahead = lookahead_table[key]; UniqueID = lookahead["UniqueID"]; just_move = lookahead["NextOperation"]; is_recover = lookahead.get("ISRECOVER", False)
            if is_recover:
                cnt_max = 0; sidx = lookahead["SIdx"]; tidx = lookahead["TIdx"]
                for key2 in ["AfterOperationSourcePath", "AfterOperationTargetPath"]:
                    paths = lookahead[key2]
                    if len(paths) == 0:
                        continue
                    cnt = 0
                    for k in range(len(paths)-1):
                        path0, path1 = paths[k], paths[k+1]
                        if path1 != path0:
                            gates.append((cnt_max + cnt + 0.01, (path0, path0), "Transfer", self.args.time_transfer+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}_after_localswap"))
                            gates.append((cnt_max + cnt + 1, (path0, path1), "RELOCATE", self.args.time_int_SWAP, (sidx, tidx), f"{UniqueID}_{uuid4().hex}_after_relocation"))
                            cnt += 1
                    if len(paths) > 1:
                        self.AfterOperationPath.append(len(paths))
                    if len(lookahead.get("AfterOperationSourcePath", [])) > 1 or len(lookahead.get("AfterOperationTargetPath", [])) > 1:
                        if lookahead.get("n_RETURN", None) is not None:
                            self.num_returns += lookahead["n_RETURN"]
                        if lookahead.get("n_RR", None) is not None:
                            self.num_redundant_returns += lookahead["n_RR"]
                continue
            manhattan_distance = get_manhattan_distance(lookahead["SPos"], lookahead["TPos"])
            self.manhattan_distance.append(manhattan_distance)
            if not just_move:
                if lookahead["SPos"] != lookahead["TPos"]:
                    self.num_crosschip_op_gates += 1
                    self.travel_distance += int(np.abs(np.array(lookahead["SPos"]) - np.array(lookahead["TPos"])).sum())
                else:
                    self.num_onchip_op_gates += 1
            self.num_cops += lookahead["Cops"]
            sidx = lookahead["SIdx"]
            tidx = lookahead["TIdx"]
            if just_move:
                Search = ["BeforeOperationSourcePath"]
            else:
                Search = ["BeforeOperationSourcePath", "BeforeOperationTargetPath"]
            cnt_max = 0
            for key2 in Search:
                cnt = 0
                idx = sidx if key2 == "BeforeOperationSourcePath" else tidx
                self.BeforeOperationPath.append(len(lookahead[key2]))
                len_data = len(lookahead[key2])-1
                for i in range(len_data):
                    if lookahead[key2][i] == lookahead[key2][i+1]:
                        continue
                    else:
                        if _is_flat_atom(idx):
                            gates.append((cnt, (lookahead[key2][i], lookahead[key2][i+1]), "RELOCATE", self.args.time_int_SWAP, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                            cnt += 1
                            continue
                        if self.atom_type[idx] == "SLM":
                            gates.append((cnt, (lookahead[key2][i], lookahead[key2][i]), "Transfer", self.args.time_transfer+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                            self.atom_type[idx] = "AOD"
                            cnt+=0.01
                        gates.append((cnt, (lookahead[key2][i], lookahead[key2][i+1]), "RELOCATE", self.args.time_int_SWAP, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                        cnt += 1
                        self.atom_type[idx] = "SLM"
                cnt_max = max(cnt_max, cnt)
            if just_move:
                continue
            if not just_move:
                opt_sp = lookahead["OptSPos"]
                opt_tp = lookahead["OptTPos"]
            if not just_move:
                if _is_flat_atom(sidx) or _is_flat_atom(tidx):
                    if opt_sp != opt_tp:
                        gates.append((cnt_max+1, (opt_sp, opt_tp), "Re-CNOT", self.args.time_int_2Q, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                        cnt_max += 1
                    else:
                        gates.append((cnt_max+0.01, (opt_sp, opt_tp), "Local CNOT", self.args.time_2Q+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                    continue
                if opt_sp != opt_tp:
                    if (self.atom_type[sidx] == "SLM"):
                        gates.append((cnt_max+0.01, (opt_sp, opt_sp), "Transfer", self.args.time_transfer+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                        cnt_max+=0.01
                        self.atom_type[sidx] = "AOD"
                    gates.append((cnt_max+1, (opt_sp, opt_tp), "Re-CNOT", self.args.time_int_2Q, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                    cnt_max+=1
                    self.atom_type[sidx] = "SLM"
                else:
                    if (self.atom_type[sidx] == "SLM" and self.atom_type[tidx] == "AOD") or (self.atom_type[sidx] == "AOD" and self.atom_type[tidx] == "SLM"):
                        gates.append((cnt_max+0.01, (opt_sp, opt_tp), "Local CNOT", self.args.time_2Q+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                    elif (self.atom_type[sidx] == "SLM" and self.atom_type[tidx] == "SLM"):
                        gates.append((cnt_max+0.01, (opt_sp, opt_sp), "Transfer", self.args.time_transfer+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                        self.atom_type[sidx] = "AOD"
                        gates.append((cnt_max+0.02, (opt_sp, opt_tp), "Local CNOT", self.args.time_2Q+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                        cnt_max+=1
                    elif (self.atom_type[sidx] == "AOD" and self.atom_type[tidx] == "AOD"):
                        gates.append((cnt_max+0.01, (opt_sp, opt_tp), "Local CNOT", self.args.time_2Q+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}"))
                        self.atom_type[sidx] = "SLM"
            for key2 in ["AfterOperationSourcePath", "AfterOperationTargetPath"]:
                paths = lookahead[key2]
                if len(paths) == 0:
                    continue
                cnt = 0
                for k in range(len(paths)-1):
                    path0, path1 = paths[k], paths[k+1]
                    if path1 != path0:
                        if _is_flat_atom(sidx) or _is_flat_atom(tidx):
                            gates.append((cnt_max + cnt + 1, (path0, path1), "RELOCATE", self.args.time_int_SWAP, (sidx, tidx), f"{UniqueID}_{uuid4().hex}_after_relocation"))
                            cnt += 1
                            continue
                        gates.append((cnt_max + cnt + 0.01, (path0, path0), "Transfer", self.args.time_transfer+self.args.time_move, (sidx, tidx), f"{UniqueID}_{uuid4().hex}_after_localswap"))
                        gates.append((cnt_max + cnt + 1, (path0, path1), "RELOCATE", self.args.time_int_SWAP, (sidx, tidx), f"{UniqueID}_{uuid4().hex}_after_relocation"))
                        cnt += 1
                if len(paths) > 1:
                    self.AfterOperationPath.append(len(paths))
        gates = sorted(gates, key=lambda x: x[0])
        logger.info(f"IR table interpretation completed with {len(gates)} gates")
        return gates