use std::{env, fs, path::Path};

use limerick_core::{
    config::NpcConfig,
    game_loop::save::load_fresh_world_and_npcs,
    game_mod::GameMod,
    ipc::prepare_npc_conversation_turn,
    npc::{LanguageSettings, NpcId},
};
use serde::Serialize;

#[derive(Serialize)]
struct Capture<'a> {
    engine_revision: &'a str,
    mod_path: &'a str,
    npc_id: u32,
    npc_name: String,
    prompt_id: usize,
    request: &'a str,
    system: String,
    user: String,
}

const REQUESTS: [&str; 24] = [
    "Good morning. What brings you out so early?",
    "Could you tell me where the road to the market begins?",
    "I have come into the parish today and know no one. Might I ask your name?",
    "How has the harvest been this year?",
    "Would you know where a traveller might find a night's lodging?",
    "I heard a cart overturned near the bridge. Is everyone safe?",
    "What work keeps you occupied through the day?",
    "I have a small parcel for someone in the village. Can you help me find them?",
    "The rain has held off, at least. Do you think it will last?",
    "I am looking for the smith. Is his forge far from here?",
    "Have you heard any news from the road to Roscommon?",
    "I could use a quiet place to rest and warm myself. Where should I go?",
    "You seem troubled. Is something weighing on your mind?",
    "Would you share a little about this place and the people who live here?",
    "I am short of food for the journey. Is there somewhere nearby to buy bread?",
    "What do you make of the new notice posted by the chapel?",
    "I have lost my way. Which path leads back toward the main road?",
    "Could you explain what happened at the fair yesterday?",
    "I am searching for honest work. Have you heard of anyone needing a hand?",
    "Do you know whether the priest is at home this morning?",
    "That is a fine wool shawl. Was it made here in the parish?",
    "I have been walking since dawn. May I sit a moment and catch my breath?",
    "How do folk here usually mark the feast day?",
    "I must send word to my family. Is there a post or messenger nearby?",
];

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        return Err("usage: prompt-export MOD_PATH ENGINE_REVISION OUTPUT_JSONL".into());
    }
    let mod_path = &args[1];
    let revision = &args[2];
    let output = Path::new(&args[3]);
    let game_mod = GameMod::load(Path::new(mod_path))?;
    let (mut world, mut manager) = load_fresh_world_and_npcs(Some(&game_mod), Path::new(mod_path))?;
    let mut locations = world.graph.location_ids();
    locations.sort_by_key(|id| id.0);
    let mut speakers: Vec<(NpcId, limerick_core::world::LocationId)> = Vec::new();
    for location in locations {
        for npc in manager.npcs_at(location) {
            if !speakers.iter().any(|(id, _)| *id == npc.id) {
                speakers.push((npc.id, location));
            }
        }
    }
    speakers.sort_by_key(|(id, _)| id.0);
    speakers.truncate(3);
    if speakers.len() < 3 {
        return Err(format!("authored mod has only {} scheduled NPCs", speakers.len()).into());
    }
    let mut lines = String::new();
    for (index, request) in REQUESTS.iter().enumerate() {
        let (speaker, location) = speakers[index / 8];
        world.player_location = location;
        let setup = prepare_npc_conversation_turn(
            &world,
            &mut manager,
            request,
            speaker,
            &[],
            false,
            &LanguageSettings::english_only(),
            &NpcConfig::default(),
        ).ok_or("engine returned no NPC conversation setup")?;
        let capture = Capture {
            engine_revision: revision,
            mod_path,
            npc_id: speaker.0,
            npc_name: setup.npc_name,
            prompt_id: index,
            request,
            system: setup.system_prompt,
            user: setup.context,
        };
        lines.push_str(&serde_json::to_string(&capture)?);
        lines.push('\n');
    }
    fs::write(output, lines)?;
    println!("wrote 24 production prompt captures to {}", output.display());
    Ok(())
}
