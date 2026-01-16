#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "tactical_generated.h"

namespace py = pybind11;
using namespace Tactical;

// Helper: Serialize a Tactical Update into bytes
py::bytes pack_update(std::string s, std::string p, std::string o, 
                      std::map<std::string, uint64_t> clock_map, 
                      std::string source) {
    
    flatbuffers::FlatBufferBuilder builder(1024);

    // 1. Serialize Vector Clock Map -> FlatBuffer Vector
    std::vector<flatbuffers::Offset<VectorClockEntry>> clock_offsets;
    
    for (auto const& [node_id, seq] : clock_map) {
        auto id_str = builder.CreateString(node_id);
        auto entry = CreateVectorClockEntry(builder, id_str, seq);
        clock_offsets.push_back(entry);
    }
    
    auto clock_vec = builder.CreateVector(clock_offsets);
    
    // 2. Serialize Strings
    auto s_off = builder.CreateString(s);
    auto p_off = builder.CreateString(p);
    auto o_off = builder.CreateString(o);
    auto src_off = builder.CreateString(source);
    
    // 3. Create Update Table
    auto update = CreateUpdate(builder, s_off, p_off, o_off, clock_vec, src_off);
    
    // 4. Wrap in Message
    auto msg = CreateMessage(builder, Payload_Update, update.Union());
    
    builder.Finish(msg);
    
    return py::bytes((char*)builder.GetBufferPointer(), builder.GetSize());
}

// Helper: Parse bytes back to Python Dict
py::dict unpack_to_dict(std::string data) {
    // Safety check
    flatbuffers::Verifier verifier((const uint8_t *)data.c_str(), data.length());
    if (!VerifyMessageBuffer(verifier)) {
        return py::dict();
    }

    auto msg = GetMessage(data.c_str());
    py::dict res;

    if (msg->type_type() == Payload_Update) {
        auto update = msg->type_as_Update();
        res["type"] = "UPDATE";
        res["s"] = update->s()->str();
        res["p"] = update->p()->str();
        res["o"] = update->o()->str();
        res["source"] = update->source()->str();
        
        // Unpack Vector Clock
        py::dict clock_dict;
        if (update->clock()) {
            for (auto entry : *update->clock()) {
                // FIX: Use .c_str() to allow Pybind11 to use it as a key
                clock_dict[entry->node_id()->c_str()] = entry->seq();
            }
        }
        res["clock"] = clock_dict;
    } 
    else if (msg->type_type() == Payload_Heartbeat) {
        auto hb = msg->type_as_Heartbeat();
        res["type"] = "HEARTBEAT";
        res["id"] = hb->node_id()->str();
        res["port"] = hb->port();
    }
    
    return res;
}

PYBIND11_MODULE(tactical_core, m) {
    m.doc() = "Tactical C++ Core via FlatBuffers";
    m.def("pack_update", &pack_update, "Serialize Triple");
    m.def("unpack", &unpack_to_dict, "Deserialize Any Message");
}