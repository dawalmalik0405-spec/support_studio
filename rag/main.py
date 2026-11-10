from rag.services.rag_service import RAGService


def main():

    rag_service = RAGService()

    print("Starting RAG system...")

    rag_service.start()

    print("RAG system is ready.")
    print("Type 'exit' to quit.")

    try:

        while True:

            question = input("\nYou: ").strip()

            if not question:
                continue

            if question.lower() == "exit":
                break

            result = rag_service.ask(
                question
            )

            print(
                "\nAssistant: ",
                end="",
                flush=True
            )

            for token in result["answer"]:
                print(
                    token,
                    end="",
                    flush=True
                )

            print("\n")

            print("Sources:")

            for source in result["sources"]:

                source_file = source.get(
                    "source_file",
                    "Unknown"
                )

                page = source.get("page")

                if page is not None:
                    print(
                        f"- {source_file} "
                        f"(Page {page})"
                    )
                else:
                    print(
                        f"- {source_file}"
                    )

    except KeyboardInterrupt:

        print("\nStopping RAG system...")

    finally:

        rag_service.stop()

        print("RAG system stopped.")


if __name__ == "__main__":
    main()
